"""No-mock provisioning for the widget E2E.

Registers a real tenant through the live API, verifies the email via Mailpit,
creates a website + widget, and kicks off a real crawl job. Every call hits a
real backend (MongoDB, Redis, Mailpit) - nothing is stubbed or mocked.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

DEFAULT_PASSWORD = "E2ePass!2026"

_VERIFY_TOKEN_RE = re.compile(r"[?&]token=([^&\s]+)")
_MAILPIT_MESSAGES_PATH = "/api/v1/messages"


@dataclass
class ProvisionedWidget:
    """Everything the browser test needs."""

    widget_id: str
    website_id: str
    page_html: str
    email: str


class ProvisioningError(RuntimeError):
    """Raised when a live-API provisioning step fails."""


def _expect(response: httpx.Response, endpoint: str, *statuses: int) -> httpx.Response:
    if response.status_code not in statuses:
        raise ProvisioningError(f"{endpoint} -> HTTP {response.status_code}: {response.text[:500]}")
    return response


def _poll_mailpit_token(mailpit_url: str, to_email: str, timeout_seconds: int = 30) -> str:
    """Wait for the verification email in Mailpit and return the ?token value."""
    deadline = time.monotonic() + timeout_seconds
    seen: set[str] = set()
    while time.monotonic() < deadline:
        response = httpx.get(f"{mailpit_url}{_MAILPIT_MESSAGES_PATH}", timeout=5)
        if response.status_code == 200:
            for message in response.json().get("messages", []):
                message_id = str(message.get("ID", ""))
                if message_id in seen:
                    continue
                seen.add(message_id)
                recipients = [addr.get("Address", "") for addr in message.get("To", [])]
                if to_email not in recipients:
                    continue
                # The list endpoint only carries a truncated Snippet; fetch the
                # full message for the verification URL.
                full = httpx.get(f"{mailpit_url}/api/v1/message/{message_id}", timeout=5)
                if full.status_code == 200:
                    match = _VERIFY_TOKEN_RE.search(full.json().get("Text", ""))
                    if match:
                        return match.group(1)
        time.sleep(1)
    raise ProvisioningError(f"verification email for {to_email} not found in Mailpit")


def _wait_ready(
    client: httpx.Client,
    website_id: str,
    headers: dict[str, str],
    timeout_seconds: int = 300,
) -> None:
    """Poll `GET /api/websites` until the website has embedded knowledge.

    The crawl marks the website `ready` as soon as documents are stored, then
    the knowledge pipeline embeds them (raising `knowledge_chunks`). The widget
    chat needs both: `validate_chat` rejects a non-`ready` website and the RAG
    pipeline needs chunks to retrieve from.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get("/api/websites", headers=headers)
        if response.status_code == 200:
            for website in response.json():
                if website.get("id") != website_id:
                    continue
                if website.get("status") == "ready" and website.get("knowledge_chunks", 0) > 0:
                    return
                break
        time.sleep(3)
    raise ProvisioningError(
        f"website {website_id} never became ready with embedded chunks "
        f"(status: {response.status_code})"
    )


def provision_widget(
    *,
    api_base_url: str,
    mailpit_url: str,
    widget_script_url: str,
    email: str,
) -> ProvisionedWidget:
    """Provision a real tenant + widget and return the embed page HTML."""
    client = httpx.Client(base_url=api_base_url, timeout=30)

    # 1. Register (real user row in MongoDB).
    short = email.split("@")[0]
    _expect(
        client.post(
            "/api/auth/register",
            json={"name": f"E2E {short}", "email": email, "password": DEFAULT_PASSWORD},
        ),
        "POST /api/auth/register",
        201,
    )

    # 2. Verify the email via the token Mailpit captured (real email path).
    token = _poll_mailpit_token(mailpit_url, email)
    _expect(
        client.post("/api/auth/verify-email", json={"token": token}),
        "POST /api/auth/verify-email",
        200,
    )

    # 3. Login for an access token.
    login = _expect(
        client.post(
            "/api/auth/login",
            json={"email": email, "password": DEFAULT_PASSWORD},
        ),
        "POST /api/auth/login",
        200,
    )
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # 4. Create a website + widget (real rows in MongoDB).
    website = _expect(
        client.post(
            "/api/websites",
            json={"name": f"E2E Site {short}", "url": "https://example.com"},
            headers=headers,
        ),
        "POST /api/websites",
        201,
    )
    body = website.json()
    widget_id = body["widget"]["widget_id"]
    website_id = body["website"]["id"]

    # 5. Start a real crawl (worker crawls, then enqueues per-document
    #    embedding jobs; embeddings need a real GEMINI_API_KEY).
    _expect(
        client.post(f"/api/websites/{website_id}/crawl", headers=headers),
        f"POST /api/websites/{website_id}/crawl",
        202,
    )

    # 6. Wait for the pipeline to finish: the website must be `ready` AND have
    #    embedded chunks, otherwise the widget reports "still being set up"
    #    (WEBSITE_NOT_READY) or only the no-context fallback.
    _wait_ready(client, website_id, headers)

    return ProvisionedWidget(
        widget_id=widget_id,
        website_id=website_id,
        page_html=_build_page(widget_id, widget_script_url, api_base_url),
        email=email,
    )


def _build_page(widget_id: str, widget_script_url: str, api_base_url: str) -> str:
    """Return the widget embed test page (self-contained HTML).

    The embed script carries `data-api-base-url` so the widget talks to the
    live API regardless of the page's own origin. The widget mounts into a
    *closed* shadow root, which Playwright CSS selectors cannot pierce; before
    the bundle loads the page patches `attachShadow` to keep a reference
    (`host.__shadow`) that the test uses for assertions and interaction.
    Nothing about the widget's behaviour is altered - the closed-root
    reference is purely for test visibility.
    """
    hook = (
        "<script>(function(){"
        "var orig=HTMLElement.prototype.attachShadow;"
        "HTMLElement.prototype.attachShadow=function(init){"
        "var root=orig.call(this,init);this.__shadow=root;return root;"
        "};})();</script>"
    )
    embed = (
        f'<script src="{widget_script_url}" data-widget-id="{widget_id}" '
        f'data-api-base-url="{api_base_url}/api/widget/v1" defer></script>'
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Widget E2E</title></head>'
        f"<body><h1>Widget E2E host page</h1>{hook}{embed}</body></html>"
    )
