# AI Response Truncation — Forensic Audit

Date: 2026-09-13
Scope: READ-ONLY forensic audit. No source/config files were modified. Reproduction of
long-answer truncation with live providers (§14) is BLOCKED (no provider credentials
available in this environment; the worker container crash-loops on
`ProviderConfigurationError`). Analysis is CODE + TEST/TEST-FIXTURE evidence only, with
RUNTIME evidence explicitly marked as such.

---

## 1. Executive Verdict

**RUNTIME VALIDATION REQUIRED.**

The single most likely mechanism for "AI answers sometimes genuinely stop/cut in the
middle" is a **provider-side output limit stop that is indistinguishable from a normal
completion**: the app never inspects a provider's `finish_reason`, so a
`MAX_TOKENS`/`length` (or `SAFETY`/`RECITATION`) stop terminates the stream cleanly and
is reported all the way to the client as `done {status: "completed"}`.

Code-level facts (CONFIRMED):

- `finish_reason` is **never read anywhere** in the repository (grep for
  `finish_reason|stop_reason|MAX_TOKENS|max_completion_tokens|max_tokens` returns zero
  matches across `backend/` and `apps/`).
- The primary provider (Gemini, `["gemini","groq","openrouter"]` order) is capped at
  `CHAT_MAX_OUTPUT_TOKENS`, which the checked-in production env sets to **512**
  (`.env.production`; dev env 1024). A 512-token answer that the model would naturally
  write longer ends mid-sentence and is treated as success.
- The OpenAI-compatible providers (Groq/OpenRouter) send **no `max_tokens` at all**, so
  their output ceiling is the provider/API default, outside the app's control, and
  equally invisible.
- Every downstream layer (RAG accumulation, SSE transport, widget accumulation,
  persistence, dashboard API) is byte-faithful: each provably preserves whatever the
  provider emitted.

Because an actual capped/stopped answer in production has not been observed with its
`finish_reason`/token data in this environment, the concrete hypothesis (FINDING 2,
"answer cut at the app-configured output cap") is classified **D — POSSIBLE BUT
UNCONFIRMED**, and the invisibility that would hide it is classified **C — OBSERVABILITY
GAP (CONFIRMED)**. The honest verdict is therefore RUNTIME VALIDATION REQUIRED, not
CONFIRMED AI OUTPUT TRUNCATION — proving real truncation end-to-end requires the
instrumentation steps in §15.

---

## 2. Complete Pipeline

The page path for a widget chat turn (identical generation pipeline for the dashboard
`/api/chat/stream`):

```
User question
  -> widget: streams/chat.ts startAssistantTurn
  -> widget: streams/client.ts POST /api/widget/v1/chat (SSE, 401 single-retry)
  -> backend: api/routes/widget.py:196 -> ensure_terminal_done(rag.stream_answer(...))
  -> backend: api/sse.py stream_answer_with_usage(buffer_ms=50, heartbeat=15s)
       -> buffered_stream_with_disconnect (coalesce + flush) -> with_heartbeats (: ping)
  -> backend: services/chat/rag_service.py stream_answer
       retrieval -> context -> generation:
  -> backend: ai/router.py FallbackGenerationClient (pre-stream fallback chain)
  -> provider clients (chain order gemini -> groq -> openrouter):
       backend/ai/gemini.py GoogleGeminiClient (gemini-2.5-flash)
       backend/ai/providers/groq.py      (openai/gpt-oss-20b)
       backend/ai/providers/openrouter.py(meta-llama/llama-3.3-70b-instruct)
       (both share backend/ai/providers/openai_compat.py wire parsing)
  -> back up: deltas joined -> ChatMessage.content persisted -> done frame
  -> widget onDelta appendDelta (content += delta) -> bubbles renderer
  -> dashboard API /api/conversations returns full stored content
```

First _detectable-in-code_ loss boundary:

> **`backend/ai/providers/openai_compat.py:104-110` and `backend/ai/gemini.py:205-207`**
> — the provider stream iterators discard each chunk's `finish_reason`. The answer can
> become "incomplete vs. the model's intent" at the provider (output cap / safety stop);
> from that point on nothing in the system can tell the difference between "answer
> complete" and "answer cut" (§10).

---

## 3. Provider Analysis

### Gemini — `backend/ai/gemini.py`

- Modem: `gemini-2.5-flash` (settings `gemini_model`).
- Uses the Google GenAI async SDK `client.aio.models.generate_content_stream` (shared in the
  prior audit; entry: `_stream_generate_once` gemini.py:159-217).
- Request always sets a config:
  - `max_output_tokens` = `settings.chat_max_output_tokens` (gemini.py:74,175). Default
    `backend/core/config.py:450` is **4096**; prod/dev env override to **512** / **1024**
    (`.env.production` / `.env.development`) — see §4.
  - `temperature` 0.2, `top_p` 0.95.
- Loop (`gemini.py:180-213`): per-chunk `await asyncio.wait_for(stream.__anext__(), timeout=...)`.
  First chunk timeout = `generation_first_token_timeout_seconds` (10s; default 10) →
  `GenerationUnavailableError` → router falls through to next provider (no retry).
  Later-chunk timeout = `generation_timeout_seconds` (60s in `.env.production`; default 30)
  → `GenerationError` → mid-stream, so the router re-raises (no fallback) and the RAG
  service emits an SSE `error` (§5).
- **`chunk.text` is yielded if present; `chunk.candidates[0].finish_reason` is never
  read.** A `MAX_TOKENS` / `SAFETY` / `RECITATION` / `OTHER` stop looks identical to a
  natural `STOP`. Usage is captured from `chunk.usage_metadata` only (input/output token
  counts).
- Retry policy: `llm_max_retries` (2) with exponential backoff, but **no retry once any
  delta was emitted** (`emitted_any` guard gemini.py:128-155) — a mid-stream failure
  surfaces as an error rather than restarting the answer.

### Groq — `backend/ai/providers/groq.py`

- OpenAI-compatible `POST /chat/completions` streaming; shared wire parser with
  OpenRouter.
- **Payload has no `max_tokens` / `max_completion_tokens`** (`build_chat_payload`
  openai_compat.py:45-74 only sets `model`, `messages`, `stream: True`,
  `stream_options.include_usage: True`). Output ceiling = Groq/API default, unknown to
  the app.
- `client.stream("POST", ..., timeout=ai_provider_timeout_seconds)` (groq.py:78-88) —
  the httpx timeout applies per read while consuming the SSE body. In `.env.production`
  `AI_PROVIDER_TIMEOUT_SECONDS=60`; the code default (config.py:260) is 10.
- Status >= 400 → `map_openai_http_error`; httpx timeout → `GenerationUnavailableError`;
  transport error → `GenerationUnavailableError` (groq.py:102-105). Usage captured from
  the `include_usage` trailer chunk.

### OpenRouter — `backend/ai/providers/openrouter.py`

- Structurally identical to Groq (same shared helpers, base URL
  `https://openrouter.ai/api/v1/chat/completions`). Same no-`max_tokens` payload, same
  per-read 60s(default 10) httpx timeout, same error mapping.

### Shared parser — `backend/ai/providers/openai_compat.py`

- `iter_openai_sse` (77-110): iterates `response.aiter_lines()`, skips non-`data:`
  lines, stops at `data: [DONE]`, JSON-parses each chunk, extracts
  `choices[0].delta.content`. **`choices[0].finish_reason` is never read** — the sample
  wire chunk in tests carries `"finish_reason": None` (tests/test_groq_provider.py:24,
  tests/test_openrouter_provider.py:24), but the parser ignores the field. A
  `finish_reason: "length"` chunk therefore passes through as if natural.
- `iter_openai_first_token_guarded` (113-147): wraps only the FIRST item in a
  `first_token_timeout_seconds` guard (10s → `GenerationUnavailableError`); later reads
  rely solely on the httpx read timeout.

### Embedding providers (Jina/Cohere) and Mock

- Generation-irrelevant. Jina/Cohere are embedding-only (registry.py:154-158). Mock
  generation is deterministic and keyless, used only when explicitly configured offline.

---

## 4. Effective Token/Output Limits

| Layer                            | Where set                               | Value in `.env.production` | Value in `.env.development` | Default (config.py) |
| -------------------------------- | --------------------------------------- | -------------------------- | --------------------------- | ------------------- |
| Gemini output cap                | gemini.py:74,175 (`max_output_tokens`)  | **512**                    | 1024                        | 4096                |
| Groq/OpenRouter output cap       | **not sent** — provider default governs | n/a (uncontrolled)         | n/a                         | n/a                 |
| Per-chunk stall (Gemini)         | gemini.py:185-201                       | 60s                        | 60s                         | 30s                 |
| First-token (Gemini)             | gemini.py:193-198                       | 10s                        | (unset)                     | 10s                 |
| httpx per-read (Groq/OpenRouter) | openai_compat.py:41 / groq header       | 60s                        | 60s                         | 10s                 |
| Router fallback per provider     | router.py:191-194                       | pre-stream only            | same                        | same                |

Consequence: with the checked-in production env, a Gemini-served answer is hard-capped
at 512 output tokens and a cap hit is silently accepted (§1, FINDING 2). If the Groq /
OpenRouter fallback serves a turn, the app has surrendered all control of the maximum
answer length (FINDING 3).

---

## 5. Finish Reason Analysis

- **No code in the repository consumes `finish_reason`/`stop_reason`** (grep zero
  matches; `GenerationUsage` at gemini.py:33-39 carries only input/output token counts).
- The Google GenAI SDK and the OpenAI-compatible SSE both expose finish/stop reasons on
  the wire (`chunk.candidates[0].finish_reason`; `choices[0].finish_reason` in the
  OpenAI-compat stream, present even mid-stream), and both parse layers simply discard
  them.
- Behaviors that therefore look identical to success:
  - `MAX_TOKENS` / `length`: output hit the app cap (Gemini, 512 in prod) or the
    provider default (Groq/OpenRouter).
  - `SAFETY` / `RECITATION` / `OTHER*`: model-side implicit stop for content or
    recitation; final text can end abruptly.
  - Empty-generation fallback is handled (`rag_service.py:1434-1446` substitutes the
    canonical fallback + `substituted_fallback: true`), so a fully-empty cap stop is not
    silent — but a **partially-filled** cap stop is.
- Nothing downstream detects a non-`STOP` finish: `done` is built and stamped
  `status:"completed"` (sse.py:152-155), usage is billed, the answer is persisted, and
  metrics record a success (§6-8).

---

## 6. Streaming Analysis (backend SSE)

- `stream_answer_with_usage` (sse.py:352-444) wraps the RAG generator with the billing
  gate then, because `sse_buffer_ms=50` (default) > 0, uses
  `buffered_stream_with_disconnect` (sse.py:242-349): small `message` deltas coalesce
  into one frame per ≤50ms window; non-message events flush the buffer first and yield
  immediately (sse.py:322-328); trailing buffered deltas are flushed on normal
  completion (sse.py:346-348). Ordering is preserved.
- `with_heartbeats` (sse.py:64-107) emits `: ping` comments during silence (15s) — never
  before/after/instead of a frame, comments only — so proxies/browsers stay alive and
  the widget's byte-level watchdog never misfires (§7).
- `ensure_terminal_done` (sse.py:130-197) guarantees a terminal `done`; any handled
  failure is followed by `done {status:"failed"}, and a provider exception mid-stream
becomes an `error` event (rag_service.py:1421-1427). A mid-stream transport timeout
  (§3) is therefore surfaced as an error + failed done — a _visible_ cut, not a silent
  one (FINDING 4).
- Client disconnect (`request.is_disconnected()` per event, sse.py:200-217/308) stops the
  pipeline and does NOT persist the partial `ChatMessage` — this creates a _recoverable_
  non-persisted answer, but the client is gone so no silent visible truncation.

Deliverable: **the backend sends exactly the deltas the provider emitted, in order, and
always terminates.** No content loss in transport.

---

## 7. Streaming Analysis (widget)

- `apps/widget/src/core/sse.ts` `readSseStream`: byte buffer → `\n\n` frame split,
  CRLF normalization, trailing partial frame parsed, comments ignored. **Byte-level**
  inactivity watchdog re-armed on every `reader.read()` (sse.ts:106-147);
  `CHAT_STALL_TIMEOUT_MS = BACKEND_GENERATION_TIMEOUT_MS + 15s = 45s` (client.ts:41).
  Backend heartbeats every 15s keep bytes flowing, so the watchdog only fires on a
  genuinely dead connection — no premature client-side cut under normal long pauses.
  Connect timeout 30s (CHAT_CONNECT_TIMEOUT_MS, client.ts:18).
- `consumeStream` (client.ts:251-329): `sources`/`message`/`done`/`error` dispatched;
  terminal-idempotency guard (`terminalReached`) accepts exactly one outcome; a
  `done {status:"..."}` with a failed status maps onto the error path.
- `chat.ts appendDelta` does `message.content += delta` (chat.ts:188-194); the only
  `setAssistantContent` call is the canned NO_CONTEXT rewrite gated on
  `done.fallback` (mount.ts:442-446) and never happens on a normal streamed answer.
- The 1200-char display collapse (`apps/widget/src/ui/bubbles.ts`, LONG_MESSAGE_CHARS)
  is render-only with an expand control; the underlying content is intact. **This
  collapse is ACCEPTED/intentional and out of scope for this audit.**

Deliverable: **the widget accumulates exactly the bytes the backend frames carried.**
No frontend stream loss.

---

## 8. Persistence Analysis

- RAG joins all provider deltas: `answer = "".join(deltas)` (rag_service.py:1429);
  `ChatMessage.new(..., content=answer)` persisted via `_messages.create` (rag_service.py:1518-1552).
- `_strip_invalid_citations` removes only `[N]`-style markers outside the retrieved
  source range (`_CITATION_MARKER_RE = \[(\d{1,2})\], rag_service.py:2323-2349) —
  never sentence/word content.
- `validate_response` (prompt_guard.py:257-268) only logs on regex matches.
- Model field `content: str` (models/chat_message.py:36) has no length cap; MongoDB
  stores the full string.
- Conversations list API shortens only title/preview metadata
  (`_MAX_TITLE_CHARS=80`, `_MAX_PREVIEW_CHARS=140`, conversation_service.py:30-31);
  detail returns full `ChatMessage` content.
- Persistence therefore equals generation; a shortened answer stored = shortened answer
  generated by the provider.

---

## 9. Timeout Analysis

| Timer                           | Place                                       | Value                 | Effect on a slow/interrupted answer                                             |
| ------------------------------- | ------------------------------------------- | --------------------- | ------------------------------------------------------------------------------- |
| Connect / first-token guard     | gemini.py:193-198; openai_compat.py:113-147 | 10s                   | GenerationUnavailableError → router tries next provider (pre-stream)            |
| Per-chunk stall, Gemini         | gemini.py:185-201                           | 60s prod (30 default) | GenerationError mid-stream → SSE `error` + failed done (visible cut)            |
| httpx per-read, Groq/OpenRouter | groq.py:82-88 / openrouter.py:82-88         | 60s prod (10 default) | GenerationUnavailableError mid-stream → SSE `error` + failed done (visible cut) |
| Widget byte watchdog            | sse.ts:89-104                               | 45s                   | Only on zero bytes for 45s (heartbeats prevent under normal stalls)             |
| Backend heartbeat               | with_heartbeats sse.py:64-107               | 15s silent            | Keeps widgets/proxies alive; no reordering                                      |

No timeout layer truncates **silently**: every timeout that fires mid-stream results in
an SSE `error` frame and a `failed` done. The only silent truncation vector remains the
cap/safety stop of §5.

---

## 10. First Proven Loss Boundary

(NO SINGLE LOSS BOUNDARY PROVEN — the truncation cannot yet be reproduced end-to-end.)

The boundary at which the answer can first become "incomplete relative to model intent"
is inside the provider stream itself:

1. Gemini: the generation stops at `max_output_tokens` (512 in prod) — the final
   non-natural stop is at the provider boundary.
2. Groq/OpenRouter: the provider/API default caps output.
3. Any provider SAFETY/RECITATION stop ends the stream with partial text.

The first boundary where the app could observe (but currently discards) the reason for
the stop is the finish-reason drop points — **`backend/ai/providers/openai_compat.py:104-110`
and `backend/ai/gemini.py:205-207`**. Every layer downstream of these two lines is
faithful (FINDINGS 5-8), so there is no later point at which the truncation could be
detected or corrected once swallowed here.

---

## 11. Findings

### FINDING 1 — [C] OBSERVABILITY GAP (CONFIRMED): finish_reason is never captured

Code: `openai_compat.py:104-110` (`choices[0].finish_reason` ignored),
`gemini.py:205-207` (`candidates[0].finish_reason` ignored); `GenerationUsage` holds no
finish field. Grep across the repo for `finish_reason|stop_reason|MAX_TOKENS|
max_completion_tokens|max_tokens` → **zero matches**. A non-`STOP` completion is
reported as `done {status:"completed"}`, billed, persisted, and counted healthy.

### FINDING 2 — [D] POSSIBLE ROOT CAUSE / [B] CONTRIBUTING FACTOR: app-set Gemini output cap is low and a cap hit is silent

`CHAT_MAX_OUTPUT_TOKENS=512` (`.env.production`), enforced on the primary provider
(gemini.py:74,175). A 512-token answer that the model would naturally extend ends
mid-sentence and is indistinguishable from completion (FINDING 1). Default config is
4096, so this depends on deployment env — prod value 512 confirmed in the checked-in
file.

### FINDING 3 — [D] POSSIBLE BUT UNCONFIRMED: Groq/OpenRouter send no max_tokens

`build_chat_payload` (openai_compat.py:45-74) omits `max_tokens`/`max_completion_tokens`;
the output ceiling becomes the provider/API default (unknown here). Mechanism real,
magnitude unproven.

### FINDING 4 — [B] CONTRIBUTING FACTOR (CONFIRMED code-level): mid-stream transport timeouts cut with a visible error

Gemini per-chunk (60s prod) and Groq/OpenRouter per-read httpx (60s prod, 10s default)
timeouts fire after the first token → GenerationError / GenerationUnavailableError →
SSE `error` + `done failed` (visible). Not silent, but perceived as "answer cut"; also
inflates the perceived truncation rate. Router never restarts a started stream
(router.py:191-194; test_ai_router.py::test_generation_never_falls_back_after_output_starts).

### FINDING 5 — [E] DISPROVED: backend does not truncate joined answer

`answer="".join(deltas)`; citation strip is markers-only; `validate_response` logs only;
`content: str` unbounded.

### FINDING 6 — [E] DISPROVED: SSE transport loses or reorders content

Flush-before-non-message + trailing flush (test_sse.py:318,342,826,920); heartbeats
never reorder (test_sse.py:691).

### FINDING 7 — [E] DISPROVED: widget loses content

`content += delta`; no overwrite on completion; byte watchdog + heartbeats preclude
premature client timeouts. (1200-char collapse is display-only and ACCEPTED.)

### FINDING 8 — [E] DISPROVED: router produces truncated-then-complete answers

Pre-stream fallback only; mid-stream failure re-raises (never restarts).

### FINDING 9 — [C] OBSERVABILITY GAP: no per-turn length-vs-cap signal survives

`done.output_tokens` (rag_service.py:2106) and timing `delta_count` (rag_service.py:1602)
are recorded, but nothing correlates them against the active cap or persists a
`finish_reason`/`capped` flag.

---

## 12. Disproved Hypotheses

- **Backend truncates/summarizes the answer** — E (FINDING 5).
- **SSE layer drops a tail or reorders** — E (FINDING 6; buffered stream tests in
  test_sse.py and trailing-flush coverage).
- **Widget overwrites the streamed content or times out early** — E (FINDING 7;
  heartbeat bytes re-arm the 45s watchdog).
- **Router emits a truncated answer followed by a complete one** — E (FINDING 8).
- **Persistence / dashboard API truncates the stored answer** — E (FINDING 5; only list
  title/preview are shortened 80/140).
- **The 1200-char bubble collapse is the truncation** — out of scope / ACCEPTED,
  display-only with expand.

---

## 13. Runtime Evidence

Strictly separated by provenance; **no production/instrumented run occurred** in this
audit (no provider keys, worker crash-loops on ProviderConfigurationError).

CODE (source inspection):

- Provider loops + finish-reason drop points; caps and timeouts (gemini.py, groq.py,
  openrouter.py, openai_compat.py, config.py:450-467,260,624).
- RAG accumulation + persistence + empty-generation guard (rag_service.py:1421-1523).
- SSE wrappers (sse.py:130-349, 352-444).
- Widget client/parser/accumulation (client.ts, sse.ts, chat.ts, mount.ts).
- Env key names & non-empty/empty status reviewed redacted; **values never printed**.
  Provider order/models/caps/timeouts from `.env.development` and `.env.production`
  (non-secret config printed in §4).

TEST (existing suites, not modified):

- tests/test_groq_provider.py, tests/test_openrouter_provider.py — delta+usage/order;
  finish_reason only as `None` in fixtures, never asserted.
- tests/test_gemini_client.py — deltas/usage, mid-stream stall error.
- tests/test_ai_router.py, tests/test_provider_router.py — pre-stream fallback only.
- tests/test_sse.py — frame serialization, disconnect, coalescing, trailing flush,
  heartbeat ordering, terminal done/status, billing gating (826,852,886,920,950,691...).
- tests/test_rag_service.py — persisting everything, generation-failure error events,
  citation stripping (no content truncation).
- Widget: core/sse.test.ts, stream/client.test.ts, stream/chat.test.ts,
  core/mount.integration.test.ts — deltas, done/error idempotency, mid-read failure.

RUNTIME (not performed — BLOCKED):

- No finish_reason captured against a real provider.
- No correlation of a persisted mid-sentence answer with `output_tokens` = cap.
- No knowledge of actual deployed env at observation time beyond the checked-in files.
- No proxy/ingress behavior (buffering/retries) observed on the live widget path.

---

## 14. Long-Answer Reproduction

**RUNTIME REPRODUCTION BLOCKED**: no provider credentials in this environment; the ARQ
worker container crash-loops with `ProviderConfigurationError`, and no
`.env`-driven live call can be made without writing config/credentials (prohibited by
the read-only audit rules). No fabricated measurements are reported.

---

## 15. Recommended Next Investigation (no fixes)

1. **Capture finish_reason per turn.** In `_stream_generate_once` (gemini.py) read
   `candidates[0].finish_reason` off the final chunk; in `iter_openai_sse`
   (openai_compat.py) read `choices[0].finish_reason`; stash it on `GenerationUsage`
   and surface it on the `done` frame + `rag_timing` log. Then audit the rate of
   non-`STOP` finishes and their correlation with `output_tokens` ≈ the active cap.
2. **Correlate stored answers against the cap.** Query recent messages whose
   `output_tokens` equals/exceeds `CHAT_MAX_OUTPUT_TOKENS` (512 in prod) and inspect
   whether the persisted text ends mid-sentence.
3. **Establish provider defaults.** Document the real default max output for Groq
   `openai/gpt-oss-20b` and OpenRouter `meta-llama/llama-3.3-70b-instruct` when
   `max_tokens` is omitted, and whether either provider emits a final
   `finish_reason:"length"` chunk when hit.
4. **Confirm deployed env.** Verify which env file/kv-set the running production
   backend actuents 512 → confirm the cap value and provider order actually in force.
5. **Reproduce with a long-answer prompt** against each provider (with valid creds),
   capturing finish_reason + stream bytes + persisted content side by side; confirm a
   cap hit appears as `done {status:"completed"}`.
6. **Inspect the edge/proxy path** (if any) between widget and backend for SSE
   buffering/retry behavior; confirm `X-Accel-Buffering: no` is honored.
7. **Decide the product intent for answer length** versus the 512-token cap (input
   budget is 20K chars context; output cap is the only output limiter).

---

## 16. Final Root Cause

A root cause has **not** been proven without runtime data. The code-level evidence
identifies the following as the realistic root cause of "answers that genuinely stop /
cut in the middle":

- The provider emits a non-`STOP` terminal chunk (`MAX_TOKENS` on Gemini at the app-set
  512-token cap — primary provider; provider-default cap on Groq/OpenRouter where no
  `max_tokens` is sent; or a SAFETY/RECITATION stop), ending the stream with partial
  text.
- Every application layer then treats that stop as a normal completion
  (`done {status:"completed"}`, billed, persisted, rendered as final) because
  `finish_reason` is never read — the observability gap at
  `backend/ai/providers/openai_compat.py:104-110` and `backend/ai/gemini.py:205-207`.

Until finish_reason is surfaced and the output cap decision is made explicit, the system
cannot distinguish a deliberate end-of-answer from a truncation, and the symptom will
persist for any answer that approaches the effective output ceiling.

**Classification summary:**

- C (CONFIRMED gap): FINISH_REASON NOT CAPTURED (F1, F9).
- D (POSSIBLE ROOT CAUSE): app-set Gemini cap hit (F2), uncontrolled provider-default
  cap on Groq/OpenRouter (F3).
- B (CONTRIBUTING): low caps + mid-stream timeouts reading as cuts (F2, F4).
- E (DISPROVED): backend, SSE, widget, persistence, router loss.
- F (REQUIRED): live finish_reason capture + output-cap audit (§15) to confirm.
