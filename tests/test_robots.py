"""Unit tests for the robots.txt parser (Phase 4 ingestion)."""

from backend.utils.robots import RobotsTxt

ROBOTS = """User-agent: *
Disallow: /private
Allow: /private/public
Disallow: /admin
Crawl-delay: 2
Sitemap: https://acme.example/sitemap.xml

User-agent: badbot
Disallow: /
"""


def test_allow_all_default() -> None:
    assert RobotsTxt.allow_all().is_allowed("/anything")


def test_disallow_and_allow_precedence() -> None:
    robots = RobotsTxt.parse(ROBOTS)
    assert not robots.is_allowed("/private/secret")
    assert robots.is_allowed("/private/public")  # longest match wins
    assert not robots.is_allowed("/admin")
    assert robots.is_allowed("/about")
    assert robots.is_allowed("/")


def test_crawl_delay_and_sitemaps() -> None:
    robots = RobotsTxt.parse(ROBOTS)
    assert robots.crawl_delay == 2
    assert robots.sitemaps == ["https://acme.example/sitemap.xml"]


def test_only_star_agent_matches_us() -> None:
    # The badbot group must not restrict our crawler (we are `*`/webchatai).
    robots = RobotsTxt.parse(ROBOTS)
    assert robots.is_allowed("/")


def test_empty_disallow_means_allow() -> None:
    robots = RobotsTxt.parse("User-agent: *\nDisallow:\n")
    assert robots.is_allowed("/anything")


def test_garbage_content_does_not_crash() -> None:
    robots = RobotsTxt.parse("!!! not robots :( ")
    assert robots.is_allowed("/x")
    robots = RobotsTxt.parse("User-agent: *\nCrawl-delay: fast\nDisallow: /a\n")
    assert not robots.is_allowed("/a/b")
    assert robots.crawl_delay is None
