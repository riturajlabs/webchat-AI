"""FIND-05: browser sandbox flag + escape-hatch telemetry tests.

Covers the sandbox-on default (no ``--no-sandbox``), the explicit
no-sandbox escape hatch (``--no-sandbox`` appended) and the WARNING-level
structured log emitted when the escape hatch is used. Reuses the fake
Playwright/Chromium abstractions from ``test_browser_lock.py`` so no real
browser is launched and no production behavior is duplicated.
"""

import asyncio
import logging

import backend.services.ingestion.browser as browser_mod
import pytest


class _FakeBrowser:
    def __init__(self) -> None:
        self.is_connected = lambda: True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser, launches: list[dict]) -> None:
        self._browser = browser
        self._launches = launches

    async def launch(self, **kwargs: object) -> _FakeBrowser:
        # Stagger so overlapping launches would be observable under the loop.
        await asyncio.sleep(0)
        self._launches.append(kwargs)
        return self._browser


class _FakePlaywright:
    def __init__(self, launches: list[dict]) -> None:
        self._launches = launches

    async def start(self) -> "_FakePlaywright":
        return self

    @property
    def chromium(self) -> _FakeChromium:
        return _FakeChromium(_FakeBrowser(), self._launches)


class _Settings:
    def __init__(self, crawl_no_sandbox: bool) -> None:
        self.crawl_no_sandbox = crawl_no_sandbox


@pytest.fixture
def reset_browser_singletons() -> None:
    browser_mod._playwright = None
    browser_mod._browser = None
    browser_mod._launch_lock = None
    yield
    browser_mod._playwright = None
    browser_mod._browser = None
    browser_mod._launch_lock = None


async def test_sandbox_enabled_does_not_add_no_sandbox_flag(
    reset_browser_singletons, monkeypatch, caplog
) -> None:
    launches: list[dict] = []
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: _FakePlaywright(launches))
    monkeypatch.setattr(browser_mod, "get_settings", lambda: _Settings(crawl_no_sandbox=False))

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        await browser_mod.get_browser()

    assert launches == [{"headless": True, "args": ["--disable-dev-shm-usage"]}]
    assert "--no-sandbox" not in launches[0]["args"]
    assert "crawl_browser_no_sandbox_enabled" not in caplog.text
    assert any(r.levelno == logging.WARNING for r in caplog.records) is False


async def test_no_sandbox_escape_hatch_adds_no_sandbox_flag(
    reset_browser_singletons, monkeypatch, caplog
) -> None:
    launches: list[dict] = []
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: _FakePlaywright(launches))
    monkeypatch.setattr(browser_mod, "get_settings", lambda: _Settings(crawl_no_sandbox=True))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        await browser_mod.get_browser()

    assert launches[0]["args"] == ["--disable-dev-shm-usage", "--no-sandbox"]


async def test_no_sandbox_logs_warning_telemetry(
    reset_browser_singletons, monkeypatch, caplog
) -> None:
    launches: list[dict] = []
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: _FakePlaywright(launches))
    monkeypatch.setattr(browser_mod, "get_settings", lambda: _Settings(crawl_no_sandbox=True))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        await browser_mod.get_browser()

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert warns[0].name == "webchat_ai"
    assert warns[0].getMessage().startswith("crawl_browser_no_sandbox_enabled sandbox=disabled")


async def test_no_sandbox_warning_is_safe_and_structured(
    reset_browser_singletons, monkeypatch, caplog
) -> None:
    launches: list[dict] = []
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: _FakePlaywright(launches))
    monkeypatch.setattr(browser_mod, "get_settings", lambda: _Settings(crawl_no_sandbox=True))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        await browser_mod.get_browser()

    message = caplog.records[0].getMessage()
    assert "crawl_browser_no_sandbox_enabled" in message
    assert "sandbox=disabled" in message
    assert "escape_hatch=true" in message
    for token in ("://", "http://", "https://", "key=", "secret", "token=", "password"):
        assert token not in message
