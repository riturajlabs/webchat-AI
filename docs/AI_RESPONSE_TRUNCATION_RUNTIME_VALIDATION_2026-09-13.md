# AI Response Truncation Runtime Validation

Date: 2026-09-13
Phase: diagnostic / root-cause validation (NO production fix implemented).
Providers exercised with the production credential set and the exact request
construction the application uses. No secrets were logged or committed. The
diagnostic scripts live OUTSIDE the repo (`/tmp/opencode/`); the only file added
to the repository is this report.

---

## 1. Executive Verdict

**ROOT CAUSE CONFIRMED**

The primary-provider path (Gemini, `gemini-2.5-flash`) truncates long answers at the
application-configured output cap and reports the truncated result as a **successful,
completed** answer.

Runtime evidence (production env, real provider calls):

- With `CHAT_MAX_OUTPUT_TOKENS = 512`, three identical long-answer requests all
  terminated with `finishReason = MAX_TOKENS`, having emitted only **0 / 18 / 78**
  output tokens (partial or empty text, ending mid-word).
- The same prompt with a 4096 cap produced **1146** output tokens and terminated with
  `finishReason = MAX_TOKENS` — i.e. the model intends to write materially more than
  512 tokens; 512 is the binding limiter, and where it cuts is variable, which is why
  the symptom appears _intermittent_.
- A short-answer control request terminated with `finishReason = STOP` and a complete
  sentence, confirming the cap — not the model — is what stops long answers.
- Because the application never reads `finish_reason` (gemini.py:205-207,
  openai_compat.py:104-110), every one of those `MAX_TOKENS` stops would flow through
  the full pipeline as `done {status: "completed"}` — a silent truncation presented as
  success.

A second, independent truncation vector is confirmed on the fallback path:

- Groq (`openai/gpt-oss-20b`), because the application sends **no `max_tokens`**, is
  silently capped at the provider default of **2048** tokens: the long request
  terminated with `finish_reason = "length"` at exactly 2048 tokens, mid-word.

---

## 2. Reproduction Status

- **Provider** : Gemini (`gemini-2.5-flash`), Groq (`openai/gpt-oss-20b`),
  OpenRouter (`meta-llama/llama-3.3-70b-instruct`) — the three providers in the
  configured production order `["gemini","groq","openrouter"]`.
- **Environment** : local runtime executing the application's exact provider-request
  construction against live provider endpoints, using the **production** env file
  (`.env.production`) for model names, output cap, temperature, and timeouts.
- **Credentials** : available — the configured production keys were used safely
  (never printed, never committed).
- **Tests** : 5 Gemini calls + 1 verification call, 2 Groq calls + 1 verification call,
  1 OpenRouter call (9 provider interactions total).
- **Production** : the live provider API was tested (with the production key/config),
  but the full production deployment (backend service, proxies, MongoDB) was NOT
  exercised; "silent success" end-to-end is therefore inferred from the code path +
  provider runtime evidence (see §10).

---

## 3. Termination Classification

| Test                   | Provider   | Output tokens           | Finish reason | SSE terminal state (as app would produce) | Persisted length | Classification                                    |
| ---------------------- | ---------- | ----------------------- | ------------- | ----------------------------------------- | ---------------- | ------------------------------------------------- |
| long @512 (#1)         | gemini     | 0                       | MAX_TOKENS    | `done completed`                          | 0 chars          | MAX_TOKENS (empty; app would substitute fallback) |
| long @512 (#2)         | gemini     | 18                      | MAX_TOKENS    | `done completed`                          | 103 chars        | MAX_TOKENS — silent truncation                    |
| long @512 (#3)         | gemini     | 78                      | MAX_TOKENS    | `done completed`                          | 465 chars        | MAX_TOKENS — silent truncation                    |
| long @512 (verify #4)  | gemini     | 20                      | MAX_TOKENS    | `done completed`                          | 109 chars        | MAX_TOKENS — silent truncation                    |
| long @4096 (control)   | gemini     | 1146                    | MAX_TOKENS    | `done completed`                          | 6187 chars       | MAX_TOKENS — proves cap, not model, truncates     |
| short @512 (control)   | gemini     | 9                       | STOP          | `done completed`                          | 32 chars         | NORMAL_STOP (control)                             |
| long (default, no max) | groq       | 2048                    | length        | `done completed`                          | 10403 chars      | LENGTH / MAX_TOKENS — silent truncation           |
| short (default)        | groq       | 78 (incl. 60 reasoning) | stop          | `done completed`                          | 15 chars         | NORMAL_STOP (content: "2 + 2 equals 4.")          |
| long (default, no max) | openrouter | 1016                    | stop          | `done completed`                          | 5791 chars       | NORMAL_STOP (natural end)                         |

No TIMEOUT, NETWORK_ERROR, SSE_ERROR, CLIENT_ABORT, WATCHDOG, or reverse-proxy
interruption was observed in any test.

---

## 4. First Loss Boundary

**FIRST LOSS BOUNDARY:**

- Primary path (Gemini):
  `backend/ai/gemini.py` → `GoogleGeminiClient._stream_generate_once` — the provider
  closes the stream with `finishReason = MAX_TOKENS` before the answer is complete;
  the loop (gemini.py:180-213) stops at `StopAsyncIteration` and the finish reason is
  discarded at gemini.py:205-207. The content truncated is content the provider never
  emitted because of the 512-token cap.
- Fallback path (Groq/OpenRouter):
  `backend/ai/providers/openai_compat.py` → `iter_openai_sse` discards
  `choices[0].finish_reason` (openai_compat.py:104-110), so Groq's `length` stop at
  its 2048 default also becomes invisible.

For content the provider DID emit: **NO CONTENT LOSS OBSERVED** at any downstream
boundary (backend join == persisted == SSE == widget accumulation, verified by code
and existing tests) — see §9.

---

## 5. Root Cause

**Confirmed**

- `CHAT_MAX_OUTPUT_TOKENS = 512` causes Gemini-served long answers to terminate with
  `finishReason = MAX_TOKENS` mid-answer (runtime-proven, §3).
- The application hides that termination by never reading `finish_reason` (code-proven,
  forensics audit §5) and by stamping every successful stream
  `done {status: "completed"}` (`ensure_terminal_done`, sse.py:152-155), so the
  truncated answer is presented, billed, and persisted as a complete answer.

**Confirmed (secondary path)**

- Groq is silently capped at its 2048-token API default because the application does
  not send `max_tokens` (runtime-proven `finish_reason = "length"` at exactly 2048).

**Strongly suspected**

- Observer-visible "intermittency" is explained by the cap, not chance: identical
  prompts produced wildly different amounts of text before MAX_TOKENS (0/18/78/20
  tokens), because `gemini-2.5-flash` reasoning consumes the shared output budget
  unevenly — so the cut point varies per request and looks intermittent.

**Ruled out**

- Transport/SSE/persistence/frontend content loss (see §9).
- Router double-delivery of truncated-then-complete answers (pre-stream fallback only).
- Client watchdog / server timeouts as the cause (no timeout activity observed; the
  short control completed fine, and all long tests ended with a provider terminal
  reason, not a client error).

---

## 6. Provider Findings

### Gemini (`gemini-2.5-flash`) — primary provider, PRODUCTION CAP PATH

- Request built exactly as the app does
  (`max_output_tokens = CHAT_MAX_OUTPUT_TOKENS = 512`, temperature 0.2, top_p 0.95).
- Result: `finishReason = MAX_TOKENS`, output cut at the cap, frequently ending
  mid-word; sometimes almost no visible text at all. The 4096 control shows the model
  wanted 1146+ tokens. **The app's 512 cap is the root cause of visible mid-answer
  cut-off on this provider.**
- The SDK surfaces `candidates[0].finish_reason` on the final chunk; the app drops it
  (gemini.py:205-207 reads only `chunk.text` + `chunk.usage_metadata`).

### Groq (`openai/gpt-oss-20b`) — fallback path, UNCONTROLLED CAP

- App payload contains **no `max_tokens`/`max_completion_tokens`**
  (`build_chat_payload`, openai_compat.py:45-74).
- Runtime: Groq enforces a **2048-token default**; long request stopped at exactly
  2048 tokens with `finish_reason = "length"`, mid-word. Same silent-success problem.
- Note: Groq `usage.completion_tokens` includes reasoning tokens
  (`completion_tokens_details.reasoning_tokens`), confirmed in the short control
  (78 = 18 content + 60 reasoning).

### OpenRouter (`meta-llama/llama-3.3-70b-instruct`) — fallback path

- Same no-`max_tokens` payload. In this test the model finished naturally
  (`finish_reason = "stop"`, 1016 tokens), so no truncation occurred here; the lack of
  an explicit cap is still a latent risk (defaults differ per upstream model).
- Took ~52s for the long request — under the 60s per-read timeout, but a slow-mass
  provider is close to the existing transport limits.

### Other configured providers

- Jina/Cohere are embedding-only (no generation). Mock generation is deterministic and
  only used when configured offline.

---

## 7. 512 Token Hypothesis

**YES — CHAT_MAX_OUTPUT_TOKENS=512 is causing the observed cut-off.**

Evidence:

1. Same long prompt, same credentials, same model, cap 512 → `MAX_TOKENS` at 0/18/78/20
   output tokens, partial or empty text.
2. Same prompt, cap 4096 → `MAX_TOKENS` at **1146** output tokens, mid-word. The model
   would have written well past 512; only the cap changed the outcome.
3. Short control (naturally < 512 tokens) → `STOP`, complete sentence. The cap only
   cuts answers whose natural length exceeds it.

This is a deterministic cap whose visible cut point varies (due to shared reasoning
budget), which matches the "sometimes stops/cuts off mid-sentence" report.

---

## 8. Silent Success Problem

**YES — a MAX_TOKENS completion currently appears to the user as a successfully
completed answer.**

- Both provider iterators discard `finish_reason` (gemini.py:205-207,
  openai_compat.py:104-110); neither the `done` frame nor the RAG pipeline carries any
  "capped/truncated" signal.
- `ensure_terminal_done` stamps every alarm-free stream `status: "completed"`
  (sse.py:152-155); `_recording_events` bills `ai_responses` + `tokens_used` for it
  (sse.py:530-548); `RagService` persists `ChatMessage.content` and records metrics as
  success (rag_service.py:1518-1552, 1696-1699).
- Net effect: a 512-MAX_TOKENS answer (e.g. 78 tokens ending mid-word) is rendered,
  persisted, and billed exactly like a natural `STOP` answer. Only the 0-token edge
  case is not silent — the blank-generation guard substitutes
  `UNKNOWN_ANSWER_FALLBACK` (rag_service.py:1434-1446).

---

## 9. Transport Findings

| Layer                       | Content lost?                          | Evidence                                                                                          |
| --------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Provider stream             | YES — content never generated (capped) | MAX_TOKENS / length terminations (§3)                                                             |
| Backend SSE                 | NO                                     | `buffered_stream_with_disconnect` flush-before-non-message + trailing flush; tests pass           |
| Widget SSE parse/accumulate | NO                                     | `appendDelta` = `content += delta`; byte watchdog re-armed by heartbeats; widget tests pass (322) |
| Persistence                 | NO                                     | `answer = "".join(deltas)`; citation strip is marker-only; `content: str` unbounded               |
| Browser rendering           | NO                                     | 1200-char collapse is display-only with expand (accepted; unchanged)                              |

The only place content disappears is at the provider output cap — downstream layers
are byte-faithful to whatever the provider emitted.

---

## 10. Runtime vs Code Evidence

**CODE-PROVEN**

- `finish_reason` is never read (`grep finish_reason|max_tokens|MAX_TOKENS` → 0 matches).
- Gemini request sets `max_output_tokens = CHAT_MAX_OUTPUT_TOKENS` (gemini.py:74,175).
- OpenAI-compatible payload sends no `max_tokens` (openai_compat.py:58-72).
- `done {status: "completed"}` is stamped for any non-failed stream (sse.py:152-155).
- Backend/SSE/widget/persistence are content-preserving (tests below pass).

**RUNTIME-PROVEN** (this phase, live providers, production config)

- Gemini MAX_TOKENS at 0/18/78/20 and 1146 tokens; 512 cap is the binding limiter.
- Groq `length` at exactly 2048 tokens.
- OpenRouter natural `stop` at 1016 tokens.
- Short-control natural `stop` for both Gemini and Groq.
- Groq usage includes reasoning tokens.

**INFERRED**

- That those exact terminations, when produced by the real back-end pipeline, appear as
  `done {status:"completed"}` end-to-end. The provider requests were reproduced
  byte-for-byte with the app's code path, and the SSE/RAG code path is test-covered,
  but the full live backend+Mongo was not run in this phase.

**Tests run (existing, unmodified):**

- `apps/widget` vitest: 322/322 passed (incl. sse, client, chat, mount integration).
- `backend tests/test_sse.py tests/test_groq_provider.py tests/test_openrouter_provider.py`: 59 passed.
- No test currently exercises a `MAX_TOKENS`/`length` finish reason — consistent with
  the code gap; no new test was added because the isolated runtime probe (outside the
  repo) already provides the required deterministic evidence without modifying sources.

---

## 11. Recommended Fix

(Not implemented — this phase is diagnostic only.)

Minimal correct fix (two coupled parts):

1. **Surface the termination reason.** In `GoogleGeminiClient._stream_generate_once`
   read `candidates[0].finish_reason` from the final chunk and in `iter_openai_sse`
   read `choices[0].finish_reason`; add a `finish_reason` field to `GenerationUsage`,
   a `finish_reason`/`truncated` flag on the RAG `done` frame, and to the persisted
   message. This converts the silent success into an observable state.
2. **Reconcile the cap with the product.** Either raise `CHAT_MAX_OUTPUT_TOKENS`
   (code default is 4096; the 4096 control still truncated only an unusually long
   answer) or keep 512 and have the prompt instruct a hard length — but never both a
   hard 512 cap and silence about it.

For Groq/OpenRouter, when a truncation-visible policy exists, send the provider an
explicit `max_tokens` equal to the intended cap so termination is app-controlled.

---

## 12. Next Step

Implement part 1 of §11 as a minimal diagnostic-to-fix step: propagate
`finish_reason` from both provider iterators into `GenerationUsage` →
`rag_service` `done` frame (and a transient log), then re-run the same probe set
against the live providers through the full backend to observe `done` carrying
`finish_reason: MAX_TOKENS/length` instead of a bare `completed`. Only after that is
verified, decide with the product owner the target cap/policy (part 2).

---

## Appendix A — Safety

- Frozen scope respected: no `backend/workers/`, crawler, Docker/worker, bubbles.ts
  (1200 collapse intact), `CHAT_MAX_OUTPUT_TOKENS`, provider order/fallback policy,
  SSE watchdogs, or timeouts were modified.
- No commit, no push. HEAD remains `d024f2ad605084b422c1791f12d4d078af97c979`.
- Diagnostic scripts are outside the repository (`/tmp/opencode/`).
- Secret values were never printed; env files were only read by the probe at runtime.
