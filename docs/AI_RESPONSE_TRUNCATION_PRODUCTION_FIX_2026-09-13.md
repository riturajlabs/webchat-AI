# AI Response Truncation — Production Fix (2026-09-13)

| Field    | Value                                                                                                                                                     |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scope    | Silent answer truncation + per-complexity output-token cost control                                                                                       |
| Status   | **Complete** (root cause validated live, fix implemented, tests green)                                                                                    |
| Evidence | [Forensic audit](./AI_RESPONSE_TRUNCATION_FORENSIC_AUDIT_2026-09-13.md) · [Runtime validation](./AI_RESPONSE_TRUNCATION_RUNTIME_VALIDATION_2026-09-13.md) |
| Branch   | `main` (HEAD `d024f2ad605084b422c1791f12d4d078af97c979`)                                                                                                  |
| Commits  | **None** — nothing committed or pushed per instructions                                                                                                   |

---

## 1. Root cause (recap, validated live)

- **Gemini** was capped by `CHAT_MAX_OUTPUT_TOKENS=512`; `finish_reason` was
  discarded, so turns that ended `MAX_TOKENS` at 0/18/78/20 tokens were
  persisted and streamed as **silent success** (`done {status:"completed"}`).
- **Groq** received **no `max_tokens`** in the request, so the provider applied
  its own default and stopped at exactly 2048 output tokens (`length`) — again
  without any signal to the client.
- **OpenRouter** only appeared untruncated because the chosen model stopped
  naturally at ~1016 tokens; the same problem would appear as soon as a query
  exceeded the proprietary default.

The fix makes provider termination metadata first-class end-to-end and sends
an explicit, budgeted output cap to every provider.

---

## 2. What changes, briefly

1. **Provider metadata** — every generation client now reports a _normalized_
   `finish_reason`, a boolean `truncated`, and a telemetry-only
   `reasoning_tokens` count.
2. **Explicit caps** — `stream_generate(max_tokens=…)` is forwarded to Gemini
   (`max_output_tokens`), Groq and OpenRouter (`payload.max_tokens`).
3. **Cost-aware budgets** — the RAG service computes a per-query cap from the
   classified complexity (`SIMPLE`/`COMPLEX` → configurable overrides; default
   and `MEDIUM` → global `chat_max_output_tokens`).
4. **Truthful wire/UI** — `done` carries `finish_reason` + `truncated`; the
   widget shows a small notice when an answer (or its thinking) was capped.
5. **Observability** — `generation_outcome` + `generation_truncated` logs and
   `rag_timing` gain `output_cap`, `finish_reason`, `truncated`,
   `reasoning_tokens`; persistence stores the flags on the assistant message.

---

## 3. Files changed

| File                                                              | Change                                                                                                                                                                                                                                                                                                 |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `backend/ai/finish_reason.py` **(new)**                           | Normalized vocabulary (`STOP`, `MAX_TOKENS`, `LENGTH`, `SAFETY`, `RECITATION`, `OTHER`, `ERROR`, `UNKNOWN`), `TRUNCATING_FINISH_REASONS = {MAX_TOKENS, LENGTH}`, Gemini/OpenAI normalizers. Single source of truth for downstream branches.                                                            |
| `backend/ai/gemini.py`                                            | `GenerationUsage` extended (`finish_reason`, `truncated`, `reasoning_tokens`); Protocol + `_stream_generate_once` accept `max_tokens`; capture last non-`None` `finish_reason` from `candidates[0]`, `usage_metadata.thoughts_token_count`. Clean `MAX_TOKENS` end is **not** an exception (no retry). |
| `backend/ai/providers/openai_compat.py`                           | SSE iterator yields 3-tuples `(content_delta, usage, finish_reason)`; captures `choices[0].finish_reason`.                                                                                                                                                                                             |
| `backend/ai/providers/groq.py`                                    | Sends `max_tokens` when `> 0`; captures `length`→`LENGTH`, usage, `completion_tokens_details.reasoning_tokens`.                                                                                                                                                                                        |
| `backend/ai/providers/openrouter.py`                              | Same explicit `max_tokens` + finish-reason capture.                                                                                                                                                                                                                                                    |
| `backend/ai/router.py` · `backend/services/ai/provider_router.py` | `FallbackGenerationClient` / `AdaptiveProviderRouter` forward `max_tokens` to providers.                                                                                                                                                                                                               |
| `backend/ai/mock.py`                                              | Accepts `max_tokens`; reports `finish_reason="STOP"` (fakes remain green).                                                                                                                                                                                                                             |
| `backend/core/config.py`                                          | `chat_simple_max_output_tokens` / `chat_complex_max_output_tokens` (0 = fall back to global `chat_max_output_tokens`), default `4096`.                                                                                                                                                                 |
| `backend/models/chat_message.py`                                  | `finish_reason` (`str`), `truncated` (`bool`) persisted on assistant messages (model uses `extra="allow"`).                                                                                                                                                                                            |
| `backend/services/chat/rag_service.py`                            | `RetrievalResult.complexity`; `_output_budget(complexity)`; budget passed as `max_tokens`; truncation metadata → assistant message, `done` payload, `rag_timing`, plus `generation_outcome` / `generation_truncated` logs. Billing still uses real usage.                                              |
| Widget                                                            | `ChatMessage.truncated/finishReason` + `setTruncated/setFinishReason`; `mount.onDone` reads `done.truncated`/`done.finish_reason`; `syncTruncatedNotice` bubble notice (see §5); style in `styles.ts`.                                                                                                 |
| `.env.example` · `.env.production.example`                        | Document the new keys and legacy `512` guidance for production migration.                                                                                                                                                                                                                              |
| Tests                                                             | `tests/test_finish_reason.py` (new), Gemini/Groq/OpenRouter provider coverage, RAG budget + SSE + persistence coverage, widget bubble + mount integration, config + stub updates (see §7).                                                                                                             |

---

## 4. Wire protocol / SSE contract

Additive and backward-compatible. `done` keeps `status` (set by the existing
`ensure_terminal_done` in `backend/api/sse.py`, unchanged) and adds:

```json
{
  "status": "completed",
  "finish_reason": "MAX_TOKENS",
  "truncated": true,
  "output_tokens": 78
}
```

- A **truncated** turn is still `completed` (the stream _did_ finish); the
  new fields tell clients it was capped. Truncation is **never** reported as
  `error` and **never** triggers fallback.
- No duplicate `done` frame is emitted; the partial answer is fully preserved.
- `finish_reason` is one of the normalized values in §3; `truncated` is
  `true` only for `MAX_TOKENS`/`LENGTH` (a `SAFETY`/`RECITATION` stop is
  reported but not branded as truncation).

---

## 5. Widget truthfulness

- `mount.ts` on `done` reads `finish_reason`/`truncated` and marks the turn.
- `bubbles.ts` renders a small `.wc-truncated` notice —
  _“This answer was shortened because it reached the generation length limit.”_
  — **only after** a completed turn that was capped. It appears even when the
  cap consumed the entire budget on _thinking_ tokens and left no visible
  text (observed with reasoning models), so users are never left with a silent
  empty bubble.
- **Intentionally unchanged:** the accepted 1200-char `LONG_MESSAGE_CHARS`
  collapse in `apps/widget/src/ui/bubbles.ts` was **not** removed, raised or
  redesigned. It is orthogonal to provider truncation; the new notice renders
  alongside it without interaction.

---

## 6. Cost control / billing semantics

- The budget is a **ceiling, not guaranteed spend**: `estimated_cost` and
  Prometheus `llm_tokens_used` continue to count the tokens each provider
  actually reported (`input_tokens`/`output_tokens`), so a bigger cap for hard
  questions never pays for unused output. Quota accounting
  (`LLMQuotaService`) also records real usage.
- `reasoning_tokens` is **telemetry-only**. Gemini’s `thoughts_token_count`
  and Groq’s `completion_tokens_details.reasoning_tokens` are captured for
  observability but **not** added on top of billing counts (Gemini/Groq output
  billing already includes them).
- Recommended production starting values (tune from `generation_outcome` logs +
  truncation rate): `CHAT_SIMPLE_MAX_OUTPUT_TOKENS=1024–1536`,
  `CHAT_COMPLEX_MAX_OUTPUT_TOKENS=3072–4096`, `CHAT_MAX_OUTPUT_TOKENS=4096`.
  These are now the committed values in `.env.production.example`
  (`1024` / `3072` / `4096`).

---

## 7. Validation results

### Live provider probes (real keys, `/tmp/opencode/trunc_live_validate.py`)

| Provider   | Request | Cap | finish_reason | truncated | out/reasoning tokens | visible text                   |
| ---------- | ------- | --- | ------------- | --------- | -------------------- | ------------------------------ |
| Gemini     | normal  | 256 | `STOP`        | no        | 7 / 36               | yes                            |
| Gemini     | long    | 64  | `MAX_TOKENS`  | yes       | 3 / 57               | yes (16 chars)                 |
| Groq       | normal  | 256 | `STOP`        | no        | 35 / 19              | yes                            |
| Groq       | long    | 64  | `LENGTH`      | yes       | 64 / 62              | **no** (budget spent thinking) |
| OpenRouter | normal  | 256 | `STOP`        | no        | 23 / 0               | yes                            |
| OpenRouter | long    | 64  | `LENGTH`      | yes       | 64 / 0               | yes (382 chars)                |

Finding: reasoning models can consume a tight cap entirely on thinking tokens,
producing zero visible text. Truncation metadata is correct and now surfaced.

### Gates

- Backend: `pytest` — **2475 passed, 12 skipped; 0 failed** (includes new
  finish-reason, provider, RAG budget/SSE/persistence, config tests).
- `mypy` on changed backend modules — clean; `ruff check` + `ruff format --check` — clean.
- Widget: `vitest` **326 passed**, `tsc --noEmit` clean, `eslint` clean,
  `vite build` (incl. size/asset checks) green.
- Dashboard: **untouched** (frozen from prior work — verified via `git status`).

---

## 8. Migration for production

The 512-token legacy setting is the documented root cause. On deploy:

1. Set `CHAT_MAX_OUTPUT_TOKENS=4096` (or clear it to keep the 4096 default).
2. Optionally set `CHAT_SIMPLE_MAX_OUTPUT_TOKENS` / `CHAT_COMPLEX_MAX_OUTPUT_TOKENS`.
3. Redeploy backend + widget bundle; no schema migration required (message
   fields are `extra="allow"`, additive).

---

## 9. Acceptance checklist (§29 task)

- [x] Provide normalized `finish_reason` end-to-end (provider→RAG→SSE→UI→DB).
- [x] `truncated` surfaced to stream, UI notice, persistence, telemetry.
- [x] Explicit `max_tokens` sent to Gemini, Groq, OpenRouter.
- [x] Query-complexity output budget (new config, `_output_budget`).
- [x] No duplicate `done`; partial output preserved; `completed` + flags.
- [x] No auto-retry / no fallback after partial output; clean `MAX_TOKENS` end
      is not an exception.
- [x] Billing/quota uses real tokens only; reasoning tokens telemetry-only.
- [x] `docs/` required document delivered (this file) + audit/validation docs.
- [x] Environment examples updated with budget keys and 512 guidance.
- [x] Safety: no prompts/answers/keys logged; no secrets committed.
- [x] Freeze respected: no `backend/workers/`, crawler, or Docker worker edits;
      dashboard untouched; 1200-char collapse unchanged.
- [x] Nothing committed or pushed; HEAD unchanged.
