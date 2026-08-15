"""Live end-to-end widget chat verification (against the running API).

Runs the exact SDK flow: config -> mint widget session -> streaming chat,
and prints the SSE events (sources/message/done/error). Requires the API to
be up with the fixed image.

    .venv/bin/python scripts/verify_widget_chat.py
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api/widget/v1")
ORIGIN = "http://localhost:3000"
WIDGET_ID = os.environ.get("WIDGET_ID", "")
QUESTION = "What courses are offered by Indira University?"


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _resolve_widget_id() -> str:
    """Prefer WIDGET_ID env; else read the first widget's `widget_id` field
    (the API looks widgets up by the `widget_id` field, not by `_id`)."""
    if WIDGET_ID:
        return WIDGET_ID
    import pymongo

    _load_env()
    db = pymongo.MongoClient(os.environ["MONGODB_URI"])[
        os.environ.get("MONGODB_DB", "webchat_ai")
    ]
    widget = db["widgets"].find_one({})
    return str(widget["widget_id"])


def main() -> None:
    _load_env()
    widget_id = _resolve_widget_id()
    print(f"widget_id={widget_id}")
    headers = {"Origin": ORIGIN}

    with httpx.Client(base_url=API_BASE, timeout=120.0) as client:
        config = client.get(f"/config/{widget_id}", headers=headers)
        print(f"config: {config.status_code}")
        config.raise_for_status()

        session = client.post(
            "/sessions",
            headers=headers,
            json={"widget_id": widget_id, "visitor_id": "e2e-verify-visitor"},
        )
        print(f"sessions: {session.status_code}")
        session.raise_for_status()
        token = session.json()["session_token"]

        chat_headers = {**headers, "Authorization": f"Bearer {token}"}
        with client.stream(
            "POST",
            "/chat",
            headers=chat_headers,
            json={"question": QUESTION, "session_id": None, "visitor_id": "e2e-verify-visitor"},
        ) as stream:
            print(f"chat: {stream.status_code}")
            for line in stream.iter_lines():
                if not line:
                    continue
                print(line)


if __name__ == "__main__":
    main()
