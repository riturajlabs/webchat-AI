"""ARCH-02 regression: `get_browser()` launch is serialized with a lock.

Two coroutines racing on the lazy singleton must share a single Chromium
launch. Without the lock each would independently start a Playwright process.
"""

import asyncio

import backend.services.ingestion.browser as browser_mod
import pytest


class _FakeBrowser:
    def __init__(self) -> None:
        self.is_connected = lambda: True


class _FakePlaywright:
    def __init__(self, browser: _FakeBrowser, started: list[int]) -> None:
        self._browser = browser
        self._started = started

    async def start(self) -> "_FakePlaywright":
        self._started.append(1)
        return self

    @property
    def chromium(self) -> "_FakeChromium":
        return _FakeChromium(self._browser)


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser

    async def launch(self, **kwargs: object) -> _FakeBrowser:
        # Stagger so a non-locked implementation would observe overlapping
        # starts even under an event loop.
        await asyncio.sleep(0)
        return self._browser


@pytest.fixture
def reset_browser_singletons() -> None:
    browser_mod._playwright = None
    browser_mod._browser = None
    browser_mod._launch_lock = None
    yield
    browser_mod._playwright = None
    browser_mod._browser = None
    browser_mod._launch_lock = None


async def test_concurrent_get_browser_launches_exactly_once(
    reset_browser_singletons, monkeypatch
) -> None:
    """ARCH-02: N concurrent first callers share one launch, not N."""
    started: list[int] = []
    browser = _FakeBrowser()
    playwright = _FakePlaywright(browser, started)
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: playwright)

    async def acquire() -> _FakeBrowser:
        return await browser_mod.get_browser()

    results = await asyncio.gather(*[acquire() for _ in range(5)])

    assert all(result is browser for result in results)
    assert started == [1]  # exactly one async_playwright().start()


async def test_lock_does_not_block_cached_return(reset_browser_singletons, monkeypatch) -> None:
    """After the first launch the fast path returns without the lock."""
    started: list[int] = []
    browser = _FakeBrowser()
    playwright = _FakePlaywright(browser, started)
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: playwright)

    first = await browser_mod.get_browser()
    second = await browser_mod.get_browser()

    assert first is browser
    assert second is browser
    assert started == [1]
