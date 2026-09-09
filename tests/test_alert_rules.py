"""Prometheus alert rules stay consistent with the exported metrics (OBS-03).

Guards `docker/prometheus/alerts.yml`: every rule must be complete and may only
reference metric families the application actually exports, so renaming a
metric in `backend/core/metrics.py` cannot silently disable an alert.
"""

from __future__ import annotations

import re
from pathlib import Path

import backend.core.metrics as metrics
import yaml

_RULES_FILE = Path(__file__).resolve().parents[1] / "docker" / "prometheus" / "alerts.yml"

# Captures the base series name inside every `rate(<series>[...)` expression.
_RATE_BASE = re.compile(r"\brate\(([a-z_]+)\[")

_DERIVED_SUFFIXES = ("_bucket", "_sum", "_count")
_REQUIRED_RULE_KEYS = {"alert", "expr", "for", "labels", "annotations"}
_REQUIRED_ANNOTATION_KEYS = {"summary"}


def _load_rules() -> list[dict]:
    data = yaml.safe_load(_RULES_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "groups" in data
    rules = [rule for group in data["groups"] for rule in group.get("rules", [])]
    assert rules, "alerts.yml defines no rules"
    return rules


def _base_series(series: str) -> str:
    for suffix in _DERIVED_SUFFIXES:
        if series.endswith(suffix):
            return series[: -len(suffix)]
    return series


class TestAlertRuleShape:
    def test_every_rule_is_complete_and_actionable(self) -> None:
        for rule in _load_rules():
            assert _REQUIRED_RULE_KEYS <= set(rule), f"rule {rule.get('alert')!r} missing fields"
            assert rule["for"], f"rule {rule['alert']!r} must set `for`"
            severity = rule["labels"].get("severity")
            assert severity in {"warning", "critical"}, f"rule {rule['alert']!r} bad severity"
            assert _REQUIRED_ANNOTATION_KEYS <= set(rule["annotations"])

    def test_rules_pin_a_threshold_expression(self) -> None:
        for rule in _load_rules():
            assert ">" in rule["expr"], f"rule {rule['alert']!r} has no threshold comparison"


class TestAlertMetricReferences:
    def test_alert_rules_reference_only_registered_metrics(self) -> None:
        registered = set(metrics._REGISTRY)  # noqa: SLF001 - registry is the source of truth
        for rule in _load_rules():
            cited = set(_RATE_BASE.findall(rule["expr"]))
            assert cited, f"rule {rule['alert']!r} references no series"
            for series in cited:
                base = _base_series(series)
                assert base in registered, (
                    f"rule {rule['alert']!r} references {series!r} but {base!r} is not exported"
                )

    def test_bucket_references_are_histograms(self) -> None:
        for rule in _load_rules():
            for series in set(_RATE_BASE.findall(rule["expr"])):
                base = _base_series(series)
                is_histogram = isinstance(
                    metrics._REGISTRY[base],
                    metrics.Histogram,  # noqa: SLF001
                )
                if series.endswith("_bucket"):
                    assert is_histogram, f"rule {rule['alert']!r} buckets non-histogram {base!r}"
