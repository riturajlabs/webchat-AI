# Production AI Generation Failure — Hardening & Observability Report

**Document Date:** 2026-09-14  
**Audit Reference:** [`docs/AI_GENERATION_FAILURE_ROOT_CAUSE_AUDIT_2026-09-14.md`](file:///home/riturajlabs/Projects/webchat-AI/docs/AI_GENERATION_FAILURE_ROOT_CAUSE_AUDIT_2026-09-14.md)  
**Implementation Branch:** `main`  
**Target Monorepo:** WebChat AI

---

## 1. Executive Summary

This engineering report documents the implementation of production hardening for AI generation mid-stream failures and the associated error UX overhaul.

In production, an issue was observed where:

1. Retrieval completes successfully and citation sources ("Learn more" cards) are rendered.
2. Gemini begins streaming response tokens.
3. Generation halts mid-stream.
4. Backend yields an SSE `error` frame (`GENERATION_FAILED`), followed by terminal `done`.
5. The widget displays an error banner (`"Assistant couldn't finish"`) alongside the preserved partial answer.

The primary operational gap was an **observability blind spot**: upstream Gemini exceptions during streaming were captured under a generic `GenerationError("Answer generation failed: ...")` without structured metadata (exception hierarchy, timing phase, elapsed time, tokens emitted, or normalized exception category).

The second gap was in the **error UI/UX**:

- An active error banner with a `Retry` button was displayed simultaneously with a second `Retry` button inside the failed chat bubble, creating confusing duplicate actions.
- The error banner automatically auto-dismissed after 15 seconds even when an actionable correlation/reference ID was shown for support inquiries.
- The banner close button relied on a `-6px -8px 0 0` negative margin hack that misaligned with the header.
- Color contrast on error containers and borders bordered on WCAG AA thresholds.

Both gaps have been solved without violating core safety invariants:

- Zero mid-stream provider fallback (no response stitching or partial token corruption).
- Structured, zero-leak telemetry on all Gemini stream exceptions.
- Unified single-retry UX with graceful bubble retry fallback upon banner dismissal.
- Full WCAG AA contrast compliance and crisp header alignment.

---

## 2. Problem Statement (Production Failure Symptom Recap)

During live usage, visitors asking questions (e.g., query regarding course offerings) observed the chatbot begin answering before cutting off abruptly. The widget UI retained the partial response and citation cards, while rendering:

- Banner title: `"Assistant couldn't finish"`
- Banner message: `"Your answer could not be completed because the AI generation service stopped unexpectedly. The partial response has been preserved."`
- Reference code: `Reference: <uuid>`
- Multiple `Retry` actions (one in banner, one attached to the message bubble).

Forensic analysis demonstrated that the backend correctly captured the failure, avoided overwriting or clearing the partial response, and transmitted the expected `GENERATION_FAILED` SSE error frame. However, the exact upstream Google GenAI failure reason could not be diagnosed due to absence of structured telemetry in the generation stream handler.

---

## 3. Confirmed vs Unconfirmed Findings

### Confirmed

1. **Failure Occurs Mid-Stream:** Tokens were already emitted; `started_streaming` was `True`.
2. **Active Provider is Gemini:** Primary generation is routed to `GoogleGeminiClient` (`gemini-2.5-flash`).
3. **`GenerationError` Raised:** Backend raised `GenerationError(code="GENERATION_FAILED")`.
4. **Pre-stream Fallback Guard Worked:** `FallbackGenerationClient` strictly disallows switching providers after deltas have been delivered.
5. **Partial Response Persisted:** Partial tokens and sources were saved in MongoDB with status `failed`.
6. **SSE Protocol Compliant:** SSE `error` frame was delivered, followed by terminal `done`.
7. **Widget Error Taxonomy Matched:** Widget mapped `GENERATION_FAILED` to `generation_failed` with retryable flag `true`.

### Unconfirmed (Observability Gap)

- **Exact Upstream Gemini Exception Subtype:** Because Railway production logs were unavailable during the initial audit, it was unproven whether the abort stemmed from:
  - An inter-chunk socket stall exceeding the 15-second generation timeout.
  - An HTTP/2 connection reset / broken pipe from Google's edge.
  - An upstream API-level status (e.g., HTTP 503 Service Unavailable, HTTP 429 Quota).
  - A client payload / protocol parsing error (`RemoteProtocolError`).

---

## 4. Upstream Exception Classification Architecture

To resolve the root cause whenever future incidents occur, an upstream exception classifier was implemented in `backend/ai/gemini.py`: `_classify_gemini_exception(exc: BaseException) -> str`.

The classifier inspects the target exception as well as chained exceptions (`exc.__cause__` and `exc.__context__`).

### Exception Taxonomy

| Category             | Matching Criteria                                                                                                             | Meaning                                                        |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `timeout`            | `isinstance(e, (TimeoutError, asyncio.TimeoutError))` or "timeout" in class name                                              | Chunk took longer than `timeout_seconds` or first-token stall. |
| `provider_api_error` | `APIError`, `ClientError`, `ServerError`, `ResourceExhausted`, or Google GenAI SDK error modules, status codes 503, 429, etc. | Upstream Google service returned an explicit API or RPC error. |
| `connection_error`   | `ConnectionError`, `ConnectionResetError`, `BrokenPipeError`, `ConnectionRefusedError`, or "connection reset"                 | Transport socket disconnected mid-stream by peer or network.   |
| `stream_closed`      | `RemoteProtocolError`, `ClientPayloadError`, `IncompleteRead`, or "stream closed" / "eof occurred"                            | Premature EOF or HTTP/2 stream closure before completion.      |
| `network_error`      | `NetworkError`, `TransportError`, `SSLError`, `SocketError`, `gaierror`, or DNS failures                                      | Underlying network connectivity failure.                       |
| `unknown`            | Fallthrough                                                                                                                   | Unrecognized runtime error.                                    |

---

## 5. Telemetry & Observability Design

### Log Event: `gemini_stream_exception`

Whenever an exception occurs during Gemini stream generation, `_emit_stream_telemetry` logs a structured warning before the exception is propagated.

#### Telemetry Schema (`extra` payload)

```json
{
  "event": "gemini_stream_exception",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "phase": "first_token | inter_chunk",
  "started_streaming": true,
  "exception_type": "ConnectionResetError",
  "exception_category": "connection_error",
  "elapsed_ms": 1420.5,
  "output_tokens": 42,
  "finish_reason": "UNKNOWN",
  "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "timeout_seconds": 15.0
}
```

### Security & Privacy Protections

1. **Zero Secret Leakage:** The raw exception message (`str(exc)`) is never included in the structured telemetry attributes (`event`, `provider`, `model`, `phase`, `exception_type`, `exception_category`).
2. **Exception Isolation:** Telemetry emission is wrapped in an internal `try/except Exception` block so telemetry failures can never interrupt or mask the underlying generation error.
3. **No PII Logging:** Prompts, message contents, user tokens, and customer identity fields are strictly excluded.

---

## 6. Why Mid-Stream Fallback Is Prohibited

A natural question in multi-provider architectures is: _“If Gemini fails after 10 words, why not call Groq to finish the answer?”_

In WebChat AI, mid-stream fallback is **strictly prohibited** by architectural rule:

1. **Prevention of Disjoint Answer Stitching:** Large language models have different system prompt formatting, tokenizers, tone, and reasoning trajectories. Asking Provider B to "complete" a partial sentence started by Provider A produces incoherent, contradictory, or syntactically invalid prose.
2. **Context Window Contamination:** Attempting to feed Provider A's partial output as assistant prefill is unsupported or penalized by several commercial API providers (including certain Gemini and Claude endpoints).
3. **Duplicate Billing / Latency Spikes:** Calling a secondary provider from scratch after the client has already rendered 30 tokens would require either discarding the streamed tokens (causing visible UI flicker / text disappearing) or restarting from zero while the visitor is reading.
4. **Clear Failure Semantics:** Stopping cleanly with a preserved partial answer and a single `Retry` button gives the visitor transparent feedback and control to re-execute the turn cleanly.

---

## 7. Error UX Redesign Details

### 7.1 Header Alignment & Close Button

- **Before:** `.wc-banner-header` used `align-items: flex-start`, and `.wc-banner-close` had `margin: -6px -8px 0 0` (negative margin hack) to compensate for flex alignment, causing visual misalignment across zoom levels and mobile viewports.
- **After:** `.wc-banner-header` uses `align-items: center; justify-content: space-between; gap: 8px;`. The close button has clean geometry:
  `width: 28px; height: 28px; margin: 0; padding: 0; display: inline-flex; align-items: center; justify-content: center;`

### 7.2 Auto-Dismiss Policy

- **Banners with Support Reference (`requestId`):**
  Auto-dismiss after 15 seconds is **disabled**. When an error displays a support reference (e.g. `Reference: req_12345`), the visitor must be given indefinite time to copy the code or click `Retry`. The banner only clears upon explicit dismissal (`×`), clicking `Retry`, or sending a new message.
- **Banners without Reference:**
  General notices (e.g. standard transient warnings) retain the existing 15-second auto-dismiss timeout.

### 7.3 Retry De-duplication & Fallback Coordination

- **Before:** When an error occurred, both the top error banner and the failed bubble inside the scroll view showed a `Retry` button simultaneously.
- **After:**
  - When a retryable error banner is displayed, the message list receives `data-banner-active="true"`.
  - `syncRetry` inspects `list?.dataset?.bannerActive === 'true'` and active DOM banner buttons: if the banner has a retry button, the bubble's `.wc-retry-message` is suppressed.
  - A CSS safety net guarantees suppression:
    ```css
    .wc-chat-window:has(.wc-banner:not([hidden]) .wc-banner-retry:not([hidden])) .wc-retry-message,
    .wc-messages[data-banner-active='true'] .wc-retry-message {
      display: none !important;
    }
    ```
  - **Graceful Fallback:** If the visitor closes the banner (`×`), `data-banner-active` is removed and messages are re-synchronized, causing the bubble-level `Retry` button to appear so retry remains accessible.

### 7.4 Contrast & WCAG AA Compliance

- **Before:** Surface transparency mixes without background anchors risked contrast drops depending on host container styling.
- **After:** Colors are mixed against standard surface tokens (`var(--wc-surface)` in light mode, `var(--wc-surface-elevated)` in dark mode):
  - **Light mode background:** `color-mix(in srgb, var(--wc-error, #ef4444) 10%, var(--wc-surface, #ffffff))`
  - **Light mode border:** `color-mix(in srgb, var(--wc-error, #ef4444) 35%, var(--wc-surface, #ffffff))`
  - **Dark mode background:** `color-mix(in srgb, var(--wc-error, #ef4444) 16%, var(--wc-surface-elevated, #1e293b))`
  - **Dark mode border:** `color-mix(in srgb, var(--wc-error, #ef4444) 45%, var(--wc-surface-elevated, #1e293b))`
  - Contrast ratio of body text (`var(--wc-text)`) on this background exceeds 7:1 (exceeding WCAG AAA for normal text).

---

## 8. Frontend Implementation Changes

### 1. `apps/widget/src/ui/window.ts`

- In `showBanner`: Wrapped `hideTimer` in `if (!content.requestId)` so errors displaying reference IDs remain visible until dismissed.

### 2. `apps/widget/src/ui/bubbles.ts`

- In `syncRetry`: Added check for `list?.dataset?.bannerActive === 'true'` and DOM banner query. Suppresses bubble retry when banner retry is active. Exported `syncRetry` for direct testing and synchronization.

### 3. `apps/widget/src/core/mount.ts`

- In `onError`, `catch (cause)`, and `syncRenderer`: Maintained `data-banner-active` attribute on `messageList`.
- In `onDismiss`: Cleared `data-banner-active` attribute and triggered `renderMessagesNow()` to restore bubble retry as fallback.

### 4. `apps/widget/src/ui/styles.ts`

- Removed `.wc-banner` from `.wc-status-live` screen reader styling.
- Centered `.wc-banner-header`.
- Removed negative margins on `.wc-banner-close`.
- Updated `.wc-banner` and `.wc-banner-retry` colors using `color-mix` for WCAG AA compliance.
- Added CSS safety rule to hide `.wc-retry-message` when banner retry is active.

---

## 9. Backend Implementation Changes

### 1. `backend/ai/gemini.py`

- Implemented `_classify_gemini_exception`: classifies exceptions into `timeout`, `provider_api_error`, `connection_error`, `stream_closed`, `network_error`, or `unknown`.
- Implemented `_emit_stream_telemetry`: structured warning logging with timing and token count metadata.
- Updated `_stream_generate_once`:
  - Recorded `started_time = time.monotonic()`.
  - Added inter-chunk stall telemetry.
  - Added mid-stream exception telemetry before re-raising `GenerationError` (preserving `error.code = "GENERATION_FAILED"`).

---

## 10. Test Coverage & Verification Results

### Backend Tests

- `tests/test_gemini_client.py`: 17 passed
  - `test_classify_gemini_exception`: verifies taxonomy classification across timeout, API error, connection reset, protocol error, and unknown.
  - `test_mid_stream_failure_logs_structured_telemetry`: verifies structured log record with `phase="inter_chunk"`, `started_streaming=True`, and `exception_category="connection_error"`.
  - `test_telemetry_never_leaks_secrets`: verifies API keys and raw secrets do not appear in telemetry fields.
- Full backend suite: **2,496 passed**, 12 skipped, 0 failed.
- Formatting & Linting: `ruff check` and `ruff format --check` passed with 0 errors.

### Widget Tests

- `apps/widget/src/ui/window.test.ts`: 28 passed
  - `does not auto-dismiss the banner when requestId is present`: verified banner remains active after 30s.
  - `auto-dismisses the banner after 15 seconds`: verified banners without `requestId` auto-dismiss.
- `apps/widget/src/ui/bubbles.test.ts`: 44 passed
  - `suppresses per-message Retry action when banner retry is active`: verified suppression and restore on re-sync.
- `apps/widget/src/core/mount.integration.test.ts`: 21 passed
  - Mid-stream SSE failure integration test verifies single banner retry action and bubble retry fallback upon banner dismissal.
- Full widget test suite: **334 passed**, 0 failed.
- Build & Typecheck: `tsc --noEmit`, `eslint`, and `vite build` completed successfully.

---

## 11. Production Observability Runbook

### Log Query Filters

When an incident is reported with a reference ID:

#### 1. Locate the Request

```
json.request_id = "<REFERENCE_ID>"
```

#### 2. Query Stream Telemetry

```
json.event = "gemini_stream_exception"
```

#### 3. Analyze Breakdown by Category

```
SELECT json.exception_category, count(*)
FROM logs
WHERE json.event = "gemini_stream_exception"
GROUP BY json.exception_category
```

### Alerting Rules

- **P1 - Surge in Provider API / Connection Drops:**
  Alert if `count(event="gemini_stream_exception" AND exception_category IN ("connection_error", "stream_closed", "provider_api_error")) > 10` in 5 minutes.
- **P2 - Mid-Stream Stall Surge:**
  Alert if `count(event="gemini_stream_exception" AND phase="inter_chunk" AND exception_category="timeout") > 5` in 5 minutes.

---

## 12. Future Recommendations

1. **Inter-chunk Timeout Granularity:** Consider configuring inter-chunk timeouts independently from first-token timeouts (e.g. 15s for first token, 10s between subsequent deltas) once production telemetry establishes baseline token cadence.
2. **Provider Health Circuit Breaker:** If Gemini exhibits persistent connection drops over 2 consecutive minutes, trip the circuit breaker so new requests immediately use Groq / OpenRouter without waiting for initial timeout.

---

## 13. Files Modified

| File Path                                            | Change Type | Description                                                                                    |
| ---------------------------------------------------- | ----------- | ---------------------------------------------------------------------------------------------- |
| `backend/ai/gemini.py`                               | Modified    | Added exception classification, structured telemetry emission, and timing tracking.            |
| `tests/test_gemini_client.py`                        | Modified    | Added tests for classification, telemetry emission, and secret leak prevention.                |
| `apps/widget/src/ui/window.ts`                       | Modified    | Suppressed 15s auto-dismiss when `requestId` is present.                                       |
| `apps/widget/src/ui/bubbles.ts`                      | Modified    | Suppressed duplicate retry in bubbles when banner retry is active; exported `syncRetry`.       |
| `apps/widget/src/core/mount.ts`                      | Modified    | Coordinated `data-banner-active` state between banner, bubble actions, and dismissal.          |
| `apps/widget/src/ui/styles.ts`                       | Modified    | Cleaned up banner header, close button, contrast colors, and added CSS retry suppression rule. |
| `apps/widget/src/ui/window.test.ts`                  | Modified    | Added unit test for non-auto-dismissing reference banners.                                     |
| `apps/widget/src/ui/bubbles.test.ts`                 | Modified    | Added unit test for retry suppression and restoration on message list.                         |
| `apps/widget/src/core/mount.integration.test.ts`     | Modified    | Updated integration test to verify single banner retry and bubble retry fallback.              |
| `docs/AI_GENERATION_FAILURE_HARDENING_2026-09-14.md` | Added       | Hardening documentation report.                                                                |

---

## 14. Git Commit Info

- **Branch:** `main`
- **Commit Message:** `fix: harden mid-stream AI generation failures`

---

## 15. Verification Checklist

- [x] Pre-stream fallback invariant strictly preserved (no mid-stream provider switching).
- [x] Upstream exception classification taxonomy implemented and tested.
- [x] Structured telemetry logging `gemini_stream_exception` implemented without secret leakage.
- [x] Error banner auto-dismiss disabled for banners with `requestId`.
- [x] Close button negative margin hack removed and header centered.
- [x] Duplicate retry eliminated; banner retry and bubble retry coordinated with fallback.
- [x] Banner background and border contrast upgraded with `color-mix` for WCAG AA compliance.
- [x] Full test suites verified (2,496 backend pytest passed, 334 widget vitest passed).
- [x] Linter, typecheck, and build steps passing cleanly.
- [x] Documentation report completed in `docs/AI_GENERATION_FAILURE_HARDENING_2026-09-14.md`.
