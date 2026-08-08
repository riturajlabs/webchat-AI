"""Minimal robots.txt parser (docs/06 implementation plan: robots.txt + caps).

Parses the RFC 9309 subset relevant to a crawler: `User-agent`, `Allow`,
`Disallow` and `Crawl-delay`. Rules are matched longest-prefix first with the
most specific user-agent group taking precedence, mirroring the standard.
"""

from dataclasses import dataclass, field

_CRAWLER_TOKEN = "*"


@dataclass(frozen=True)
class _Rule:
    path: str
    allowed: bool


@dataclass
class RobotsTxt:
    """Parsed robots.txt for one site (defaults to allow everything)."""

    crawl_delay: float | None = None
    sitemaps: list[str] = field(default_factory=list)
    _rules: list[_Rule] = field(default_factory=list)

    @classmethod
    def allow_all(cls) -> "RobotsTxt":
        return cls()

    @classmethod
    def parse(cls, raw: str) -> "RobotsTxt":
        """Parse raw robots.txt content into a `RobotsTxt`."""
        rules: list[_Rule] = []
        sitemaps: list[str] = []
        crawl_delay: float | None = None
        group_matched = False
        group_active = False

        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # A single "#" comment may follow the field value.
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field_name, value = (part.strip() for part in line.split(":", 1))
            name = field_name.lower()
            if name == "user-agent":
                matched = value.lower() in (_CRAWLER_TOKEN, "webchatai", "webchat-ai")
                group_active = matched
                group_matched = group_matched or matched
            elif not group_active:
                continue
            elif name == "allow":
                rules.append(_Rule(path=_rule_path(value), allowed=True))
            elif name == "disallow":
                rules.append(_Rule(path=_rule_path(value), allowed=False))
            elif name == "crawl-delay":
                try:
                    crawl_delay = float(value)
                except ValueError:
                    pass
            elif name == "sitemap":
                sitemaps.append(value)
        return cls(crawl_delay=crawl_delay, sitemaps=sitemaps, _rules=rules)

    def is_allowed(self, path: str) -> bool:
        """True when this crawler may fetch `path` (longest match wins)."""
        best: _Rule | None = None
        for rule in self._rules:
            if path == rule.path or (rule.path and path.startswith(rule.path)):
                if best is None or len(rule.path) > len(best.path):
                    best = rule
        return best.allowed if best is not None else True


def _rule_path(value: str) -> str:
    """Normalize a rules field to a matchable path ('' means whole site)."""
    if not value:
        return ""
    return value if value.startswith("/") else f"/{value}"
