"""Client-IP extraction tests (TRUST_PROXY-aware, rate-limit safety)."""

from backend.api.deps import client_ip
from backend.core.config import Settings
from starlette.requests import Request


def _request(forwarded: str | None = None, host: str = "9.9.9.9") -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (host, 1234)})


def test_client_ip_uses_direct_connection_when_not_trusting_proxy(monkeypatch) -> None:
    monkeypatch.setattr("backend.api.deps.get_settings", lambda: Settings(trust_proxy=False))
    # XFF is present but must be ignored - it is spoofable.
    assert client_ip(_request(forwarded="1.2.3.4")) == "9.9.9.9"


def test_client_ip_trusts_xff_when_trust_proxy_enabled(monkeypatch) -> None:
    monkeypatch.setattr("backend.api.deps.get_settings", lambda: Settings(trust_proxy=True))
    assert client_ip(_request(forwarded="1.2.3.4, 5.6.7.8")) == "1.2.3.4"


def test_client_ip_without_xff_uses_direct_connection(monkeypatch) -> None:
    monkeypatch.setattr("backend.api.deps.get_settings", lambda: Settings(trust_proxy=True))
    assert client_ip(_request()) == "9.9.9.9"


def test_client_ip_unknown_when_no_peer(monkeypatch) -> None:
    monkeypatch.setattr("backend.api.deps.get_settings", lambda: Settings(trust_proxy=True))
    request = Request({"type": "http", "headers": [], "client": None})
    assert client_ip(request) == "unknown"
