"""MongoDB command-duration metrics listener (Phase 6, OBS-05).

Pumps synthetic PyMongo monitoring events through `MongoMetricsListener` and
checks the registry output, so the observation path is covered without a live
database. The registry is reset before/after each test.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from backend.core.database import _NOISE_COMMANDS, MongoMetricsListener
from backend.core.metrics import render_prometheus, reset_registry
from pymongo.monitoring import (
    CommandFailedEvent,
    CommandStartedEvent,
    CommandSucceededEvent,
)

_ADDR = ("localhost", 27017)
_DB = "webchat"


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_registry()
    yield
    reset_registry()


def _started(command: dict, op_id: int) -> CommandStartedEvent:
    return CommandStartedEvent(
        command,
        _DB,
        request_id=op_id,
        connection_id=_ADDR,
        operation_id=op_id,
    )


def _succeeded(op_id: int, command_name: str, ms: int) -> CommandSucceededEvent:
    return CommandSucceededEvent(
        timedelta(milliseconds=ms),
        {"ok": 1.0},
        command_name,
        request_id=op_id,
        connection_id=_ADDR,
        operation_id=op_id,
    )


def _failed(op_id: int, command_name: str, ms: int) -> CommandFailedEvent:
    return CommandFailedEvent(
        timedelta(milliseconds=ms),
        {"ok": 0.0},
        command_name,
        request_id=op_id,
        connection_id=_ADDR,
        operation_id=op_id,
    )


def test_records_successful_command_duration() -> None:
    listener = MongoMetricsListener()
    listener.started(_started({"find": "knowledge_chunks"}, 11))
    listener.succeeded(_succeeded(11, "find", 150))

    output = render_prometheus()
    assert 'mongodb_query_duration_seconds_sum{command="find"} 0.15' in output
    assert 'mongodb_query_duration_seconds_count{command="find"} 1' in output


def test_records_failed_command_duration_too() -> None:
    listener = MongoMetricsListener()
    listener.started(_started({"aggregate": "messages"}, 22))
    listener.failed(_failed(22, "aggregate", 900))

    output = render_prometheus()
    assert 'mongodb_query_duration_seconds_count{command="aggregate"} 1' in output
    assert 'mongodb_query_duration_seconds_sum{command="aggregate"} 0.9' in output


def test_heartbeat_commands_are_not_recorded() -> None:
    listener = MongoMetricsListener()
    for name, op_id in zip(_NOISE_COMMANDS, range(100, 100 + len(_NOISE_COMMANDS)), strict=True):
        listener.started(_started({name: 1}, op_id))
        listener.succeeded(_succeeded(op_id, name, 5))

    assert render_prometheus() == ""


def test_unmatched_failure_is_ignored() -> None:
    # A `succeeded`/`failed` whose `started` was never observed must not raise.
    listener = MongoMetricsListener()
    listener.failed(_failed(999, "find", 10))
    assert render_prometheus() == ""
