"""E2E fixtures: provisioning and a local page server.

The suite requires a live stack. It self-skips unless `E2E_BASE_URL` is set
(see `scripts/e2e-widget.sh`), so the regular unit-test run stays green.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest

from tests.e2e.provision import ProvisionedWidget, provision_widget

E2E_BASE_URL = os.environ.get("E2E_BASE_URL")
E2E_MAILPIT_URL = os.environ.get("E2E_MAILPIT_URL", "http://localhost:8025")
E2E_WIDGET_SCRIPT_URL = os.environ.get(
    "E2E_WIDGET_SCRIPT_URL", "http://localhost:8080/webchat-widget.iife.min.js"
)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="session")
def widget_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, ProvisionedWidget]]:
    """Provision a real tenant/widget and serve the embed test page locally."""
    served_dir = tmp_path_factory.mktemp("widget-e2e")
    # SimpleHTTPRequestHandler accepts `directory` as a constructor kwarg, but
    # __init__ always overwrites self.directory from it - a class attribute is
    # ignored - so bind it via functools.partial.
    handler = partial(_QuietHandler, directory=str(served_dir))
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"

    assert E2E_BASE_URL, "E2E_BASE_URL must be set (see scripts/e2e-widget.sh)"
    email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    provisioned = provision_widget(
        api_base_url=E2E_BASE_URL,
        mailpit_url=E2E_MAILPIT_URL,
        widget_script_url=E2E_WIDGET_SCRIPT_URL,
        email=email,
    )
    (served_dir / "index.html").write_text(provisioned.page_html, encoding="utf-8")
    page_url = f"{origin}/index.html"

    try:
        yield page_url, provisioned
    finally:
        server.shutdown()
        server.server_close()
