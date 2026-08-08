"""Shared pytest configuration.

Tests run without MongoDB, so the client's server-selection timeout is lowered
to fail fast instead of blocking for the 30s production default.
"""

import pytest
from backend.core.config import get_settings


@pytest.fixture(autouse=True)
def _fast_failing_mongo(monkeypatch):
    """Force a short server-selection timeout and refresh cached settings."""
    monkeypatch.setenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "1000")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
