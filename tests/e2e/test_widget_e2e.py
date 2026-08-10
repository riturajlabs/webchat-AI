"""Playwright widget E2E - full no-mock flow against a live stack.

Covers: widget loads, launcher opens, message sent, SSE response received,
message rendered. No mocks: real browser, real widget bundle, real API,
real MongoDB/Redis/Mailpit, real Gemini (via `scripts/e2e-widget.sh`).
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import sync_playwright

if not os.environ.get("E2E_BASE_URL"):
    pytest.skip(
        "E2E_BASE_URL is not set - bring up the stack with scripts/e2e-widget.sh",
        allow_module_level=True,
    )

E2E_ANSWER_TIMEOUT_MS = 150_000

_LAUNCHER_READY = """
() => {
  const host = document.querySelector('webchat-widget');
  const root = host && host.__shadow;
  return !!(root && root.querySelector('.wc-launcher'));
}
"""

_WINDOW_OPEN = """
() => {
  const host = document.querySelector('webchat-widget');
  const root = host && host.__shadow;
  const win = root && root.querySelector('.wc-window');
  return !!win && !win.hidden;
}
"""

_CLICK = """
(sel) => {
  const host = document.querySelector('webchat-widget');
  const root = host && host.__shadow;
  const el = root && root.querySelector(sel);
  if (!el) {
    throw new Error('widget element not found: ' + sel);
  }
  el.click();
}
"""

_FOCUS_COMPOSER = """
() => {
  const host = document.querySelector('webchat-widget');
  const root = host && host.__shadow;
  const el = root && root.querySelector('.wc-composer-input');
  if (!el) {
    throw new Error('composer input not found');
  }
  el.focus();
  return true;
}
"""

_USER_BUBBLE = """
(text) => {
  const host = document.querySelector('webchat-widget');
  const root = host && host.__shadow;
  if (!root) {
    return false;
  }
  const bubbles = root.querySelectorAll('.wc-bubble.wc-role-user');
  return Array.from(bubbles).some((b) => b.textContent.includes(text));
}
"""

_ASSISTANT_ANSWER = """
() => {
  const host = document.querySelector('webchat-widget');
  const root = host && host.__shadow;
  if (!root) {
    return false;
  }
  const bubbles = root.querySelectorAll('.wc-bubble.wc-role-assistant:not(.wc-welcome)');
  return Array.from(bubbles).some((b) => b.textContent.trim().length > 0);
}
"""

_ASSISTANT_TEXT = """
() => {
  const host = document.querySelector('webchat-widget');
  const root = host && host.__shadow;
  if (!root) {
    return '';
  }
  const bubbles = root.querySelectorAll('.wc-bubble.wc-role-assistant:not(.wc-welcome)');
  return Array.from(bubbles).map((b) => b.textContent).join('\\n').trim();
}
"""


def test_widget_full_flow(widget_env: tuple[str, object]) -> None:
    page_url, _provisioned = widget_env
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        console_errors: list[str] = []
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))
        try:
            page.goto(page_url, wait_until="domcontentloaded")

            # 1. Widget loads: the host element exists and the launcher mounted.
            #    The host is an empty custom element (zero-size box), so wait for
            #    "attached" rather than "visible".
            try:
                page.wait_for_selector("webchat-widget", state="attached", timeout=15_000)
            except Exception as exc:
                state = page.evaluate(
                    "() => ({ host: !!document.querySelector('webchat-widget'), "
                    "webchat: typeof window.WebChatWidget })"
                )
                raise AssertionError(
                    f"widget host never appeared: {state}; console: {console_errors}"
                ) from exc
            page.wait_for_function(_LAUNCHER_READY, timeout=15_000)
            assert page.evaluate(_LAUNCHER_READY) is True, f"widget not mounted: {console_errors}"

            # 2. Launcher opens the chat window.
            page.evaluate(_CLICK, ".wc-launcher")
            page.wait_for_function(_WINDOW_OPEN, timeout=10_000)
            assert page.evaluate(_WINDOW_OPEN) is True

            # 3. Message sent: type into the composer and press send.
            page.evaluate(_FOCUS_COMPOSER)
            question = "Hello from the E2E widget test"
            page.keyboard.type(question, delay=5)
            page.evaluate(_CLICK, ".wc-send")
            page.wait_for_function(_USER_BUBBLE, arg=question, timeout=10_000)
            assert page.evaluate(_USER_BUBBLE, question) is True

            # 4 + 5. SSE response received and rendered as an assistant bubble.
            page.wait_for_function(_ASSISTANT_ANSWER, timeout=E2E_ANSWER_TIMEOUT_MS)
            answer = page.evaluate(_ASSISTANT_TEXT)
            assert answer, "assistant bubble rendered but has no text"
            assert question not in answer, "assistant bubble looks like an echo of the question"
        finally:
            browser.close()
