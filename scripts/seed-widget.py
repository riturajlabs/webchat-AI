#!/usr/bin/env python3
"""Seed a real tenant + widget in a dev stack and print the embed snippet.

Reuses the live-API flow (register -> Mailpit verify -> login -> create
website + widget) that `tests/e2e/provision.py` performs, without waiting on a
crawl. The widget's config + sessions endpoints work immediately; chat reports
WEBSITE_NOT_READY until a crawl marks the website `ready` (run
`POST /api/websites/<id>/crawl` once a crawler worker is up).

Usage:
    python scripts/seed-widget.py [--email you@example.com] [--domain example.com]

Env overrides (all optional):
    API_BASE_URL          http://localhost:8000
    MAILPIT_URL           http://localhost:8025
    WIDGET_SCRIPT_URL     http://localhost:8080/webchat-widget.iife.min.js
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
MAILPIT_URL = os.environ.get("MAILPIT_URL", "http://localhost:8025")
WIDGET_SCRIPT_URL = os.environ.get(
    "WIDGET_SCRIPT_URL", "http://localhost:8080/webchat-widget.iife.min.js"
)
DEFAULT_PASSWORD = "SeedPass!2026"

_VERIFY_TOKEN_RE = re.compile(r"[?&]token=([^&\s]+)")


@dataclass
class SeedResult:
    widget_id: str
    website_id: str
    email: str


class SeedError(RuntimeError):
    """Raised when a live-API seeding step fails."""


def _expect(response: httpx.Response, endpoint: str, *statuses: int) -> httpx.Response:
    if response.status_code not in statuses:
        raise SeedError(f"{endpoint} -> HTTP {response.status_code}: {response.text[:500]}")
    return response


def _poll_mailpit_token(to_email: str, timeout_seconds: int = 30) -> str:
    """Wait for the verification email in Mailpit and return the ?token value."""
    deadline = time.monotonic() + timeout_seconds
    seen: set[str] = set()
    while time.monotonic() < deadline:
        response = httpx.get(f"{MAILPIT_URL}/api/v1/messages", timeout=5)
        if response.status_code == 200:
            for message in response.json().get("messages", []):
                message_id = str(message.get("ID", ""))
                if message_id in seen:
                    continue
                seen.add(message_id)
                recipients = [addr.get("Address", "") for addr in message.get("To", [])]
                if to_email not in recipients:
                    continue
                full = httpx.get(f"{MAILPIT_URL}/api/v1/message/{message_id}", timeout=5)
                if full.status_code == 200:
                    match = _VERIFY_TOKEN_RE.search(full.json().get("Text", ""))
                    if match:
                        return match.group(1)
        time.sleep(1)
    raise SeedError(f"verification email for {to_email} not found in Mailpit")


def seed(email: str, site_name: str, site_url: str, allowed_domains: list[str]) -> SeedResult:
    client = httpx.Client(base_url=API_BASE_URL, timeout=30)

    short = email.split("@")[0]

    created = client.post(
        "/api/auth/register",
        json={"name": f"Seed {short}", "email": email, "password": DEFAULT_PASSWORD},
    )
    if created.status_code == 201:
        # Fresh account: verify through the real Mailpit email path.
        _expect(
            client.post("/api/auth/verify-email", json={"token": _poll_mailpit_token(email)}),
            "POST /api/auth/verify-email",
            200,
        )
    elif created.status_code != 409:
        # 409 = already registered; treat as verified and reuse below.
        _expect(created, "POST /api/auth/register", 201)

    login = _expect(
        client.post("/api/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}),
        "POST /api/auth/login",
        200,
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    website = _expect(
        client.post(
            "/api/websites",
            json={"name": site_name, "url": site_url},
            headers=headers,
        ),
        "POST /api/websites",
        201,
    )
    body = website.json()
    widget_id = body["widget"]["widget_id"]
    website_id = body["website"]["id"]

    if allowed_domains:
        _expect(
            client.patch(
                f"/api/websites/{website_id}/widget",
                json={"allowed_domains": allowed_domains},
                headers=headers,
            ),
            f"PATCH /api/websites/{website_id}/widget",
            200,
        )

    return SeedResult(widget_id=widget_id, website_id=website_id, email=email)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=f"seed-{int(time.time())}@example.com")
    parser.add_argument("--domain", default="example.com")
    args = parser.parse_args()

    result = seed(
        email=args.email,
        site_name=f"Seed {args.domain}",
        site_url=f"https://{args.domain}",
        allowed_domains=["localhost", args.domain],
    )

    embed = (
        f'<script src="{WIDGET_SCRIPT_URL}" '
        f'data-widget-id="{result.widget_id}" '
        f'data-api-base-url="{API_BASE_URL}/api/widget/v1" defer></script>'
    )
    print(f"widget_id : {result.widget_id}")
    print(f"website_id: {result.website_id}")
    print(f"email     : {result.email}")
    print(f"password  : {DEFAULT_PASSWORD}")
    print(f"crawl     : POST {API_BASE_URL}/api/websites/{result.website_id}/crawl (Bearer token)")
    print("embed     :", embed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SeedError as error:
        print(f"seed-widget: {error}", file=sys.stderr)
        sys.exit(1)
