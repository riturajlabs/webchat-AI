# A–K Report: Partial Answer Persistence on Mid-Stream Generation Failure

**Date:** 2026-09-13  
**Incident root cause:** generation exception in `stream_answer` after ≥1 assistant delta  
**Affected widget query:** "which courses are provided by indira university"  
**Previous forensic:** `AI_RESPONSE_TRUNCATION_FORENSIC_AUDIT_2026-09-13.md`

---

## A — What happened (root cause)

A Gemini provider error (GENAI codes `GENERATION_FAILED` or `GENERATION_UNAVAILABLE`) was raised inside the `async for delta in self._generation.stream_generate(...)` loop at `backend/services/chat/rag_service.py:1427`, **after** at least one assistant delta had been yielded to the client and streamed to the widget.

The widget correctly received the delta (`"Indira University provides"`) and rendered a source card. The provider then threw mid-stream, the SSE error frame was yielded (`GENERATION_FAILED`), and the `except` block returned — **before the assistant message was persisted** (line 1604-1605 in the success path, never reached).

With only a `role=user` message in the database, `conversation_service._status_from_last_role()` returned `"awaiting"` (line 203-206 of `backend/services/conversations/conversation_service.py`), and the dashboard showed the conversation as **"Awaiting reply"** — even though the visitor had already seen a partial answer.

---

## B — What changed (implementation)

Three files modified. No commits, no pushes. Untracked docs preserved.

### 1. `backend/models/chat_message.py` — new `status` field

```python
CHAT_MESSAGE_STATUS_FAILED = "failed"  # module constant
```

```python
# ChatMessage field (after `truncated`)
status: str = ""
# ""  = successful/legacy turn (default)
# "failed" = generation errored after streaming a partial answer
```

**Rationale for representation choice:**

- `extra="allow"` on `ChatMessage` means extra fields already round-trip through MongoDB; adding an explicit named field makes the failure marker self-documenting without a schema migration.
- `"failed"` matches the existing SSE wire vocabulary (`done.status: "failed"` / widget `errorEvent.status === 'failed'`), so no new enum was invented.
- `finish_reason` is left as `""` (empty/default) rather than `FINISH_REASON_ERROR` per the constraint "finish_reason if known; otherwise do not fabricate one" — the provider did not return a terminal reason on a mid-stream exception.
- `truncated=False` — the stream was not capped by a token limit; it failed.
- `input_tokens`/`output_tokens`/`estimated_cost` remain zero — failed generations are non-billable by the existing invariant (line 1522: "Failed generations never reach this line, so errors stay non-billable by construction").

**Dashboard impact:** The conversation aggregate `_status_from_last_role` (line 203-206 of `conversation_service.py`) maps any `last_role == assistant` → `"answered"`. Persisting the partial assistant turn flips the status from `"awaiting"` to `"answered"`. **No change to conversation_service.py was required** for the primary fix. The aggregate currently cannot visually distinguish "failed partial" from "answered complete" — if the dashboard later needs this distinction, the change would be: expose `status` in `ConversationMessageOut` (backend/api/routes/conversations.py:107) + render in dashboard. Not required for the core fix.

---

### 2. `backend/services/chat/rag_service.py` — persist partial on failure

**New helper:** `RagService._persist_partial_answer()` (lines 634-699 after edit)

Key properties of the helper:

- **Guard:** returns early if joined partial is empty (never persists an empty assistant turn)
- **Best-effort:** entire persistence block is wrapped in its own `try/except`; on failure, the original generation failure remains the only signal to the client (no masking)
- **Non-billing:** tokens/cost remain zero, `usage.increment()` is never called for failed turns
- **Session touch:** `self._sessions.touch()` is called in `asyncio.gather` with `return_exceptions=True` so conversation ordering stays recent without blocking the error path
- **Latency metadata:** `response_time`, `latency_generation_ms`, `latency_ttft_ms` are set for diagnostic value; `sources` are attached so the dashboard shows the source card the visitor already saw

**Wiring (exception handler, lines 1512-1527 after edit):**

```python
except Exception as exc:
    await self._stop_history_task(history_task)
    logger.exception("answer generation failed (session=%s)", session.session_id)
    if deltas:                                          # ← only after ≥1 delta
        await self._persist_partial_answer(...)
    yield _error_event(_error_code(exc), _safe_message(exc))
    record_chat_failure(reason="generation_error")
    record_llm_failure(code=_error_code(exc))
    return
```

**Order:** log → persist → error → return. This matches the desired sequence: provider exception → persist partial → error → return. The `ensure_terminal_done` wrapper in `sse.py` then emits `done{status:"failed"}` (no fake `done{completed}`).

**SSE contract preserved:** sources, message deltas, error, terminal done — unchanged for all existing paths.

---

### 3. `tests/test_rag_service.py` — 8 regression tests

All 8 scenarios explicitly tested. 10 tests in the new block (including reassertion of the pre-first-delta guard).

| #   | Test                                                               | What it verifies                                                                                                               |
| --- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `test_failure_before_first_delta_persists_nothing_partial`         | Provider error before any delta → no assistant row persisted, no status marker, error emitted                                  |
| 2   | `test_failure_after_one_delta_persists_partial_answer`             | 1 delta → exact content persisted, `status=failed`, `finish_reason=""`, `truncated=False`, tokens 0, no usage                  |
| 3   | `test_failure_after_multiple_deltas_persists_full_partial_content` | Multiple deltas → full concatenated content persisted, no content loss                                                         |
| 4   | `test_normal_stop_unchanged_and_not_marked_failed`                 | STOP path unchanged, `status=""`                                                                                               |
| 5   | `test_max_tokens_truncation_unchanged_no_duplicate_record`         | MAX_TOKENS unchanged, `truncated=True`, `finish_reason="MAX_TOKENS"`, `status=""`, exactly one assistant record                |
| 6   | `test_partial_failure_leaves_dashboard_conversation_not_awaiting`  | After partial failure, `ConversationService.get_conversation().status == "answered"` (not "awaiting")                          |
| 7   | `test_partial_persist_failure_does_not_mask_generation_failure`    | If message persistence fails, original `GENERATION_FAILED` error is still the primary SSE signal                               |
| 8   | `test_retry_creates_fresh_generation_without_duplicating_partial`  | Successful retry after a failure creates a new user+assistant pair; the previous partial stays `status=failed`, no duplication |

---

## C — What is preserved (constraints honored)

| Constraint                               | How                                                                                            |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Worker/crawler/embedding/Docker frozen   | No changes                                                                                     |
| AI output budgets unchanged              | `CHAT_MAX_OUTPUT_TOKENS` / `_output_budget` untouched                                          |
| Gemini thinking policy unchanged         | No `.env.production` change                                                                    |
| 1200-char widget collapse unchanged      | Widget code untouched                                                                          |
| Normal success/MAX_TOKENS path unchanged | Verified in tests #4, #5; full suite green                                                     |
| No provider fallback after streaming     | `router.py:194-197` untouched                                                                  |
| FAILURE NOT HIDDEN — SSE stays truthful  | `error` + terminal `done{status:"failed"}`; partial fail persisted but not reported as success |
| Only persist when deltas non-empty       | Guard `if deltas:` in exception handler; helper early-returns on empty join                    |
| No fabricated finish_reason              | `finish_reason` left `""` on partial rows                                                      |
| `truncated=False` unless provider capped | Never set on failure rows                                                                      |
| No API contract change                   | `ConversationMessageOut` unchanged; `status` is additive                                       |
| SSE terminal states preserved            | `error` → `done{status:"failed"}` via `ensure_terminal_done`; no fake `completed` done         |
| Untracked docs preserved                 | Verified `git status` — `docs/*` untracked, not touched                                        |

---

## D — What could still go wrong (known gaps)

1. **Exact provider failure subtype unknowable.** Production (Railway API + Atlas + Upstash + Vercel widget) is unreachable from this session. We know the SSE error code was `GENERATION_FAILED` or `GENERATION_UNAVAILABLE` but not the specific Gemini SDK exception type or whether it was a timeout, quota, or transient RPC error. Railway logs (`logs.railway.app`) are the authoritative source for the exact stack trace.

2. **Session touch changes ordering.** A failed turn now bumps the conversation's `last_activity` via `touch()`. On a large tenant conversation list, this makes failed conversations move up — correct for "recently active" but a behavioral change from the previous no-touch failure path.

3. **Dashboard cannot yet visually distinguish failed-partial vs. answered-complete.** The conversation aggregate status stays `"answered"` for both. A dashboard improvement (showing a partial-failure badge) would require exposing the new `status` field through `ConversationMessageOut` and updating the React UI — a separate, optional follow-up.

4. **No idempotency guard for partial persistence.** If the same `stream_answer` invocation were to fail twice (e.g., a timeout + retry within the same request), two partial assistant rows could be written. In practice this does not occur because each `stream_answer` invocation is a separate generator; an exception terminates the generator permanently.

---

## E — Production deployment sequence (when ready)

1. Deploy backend (Railway): `rag_service.py` + `chat_message.py` changes. No migration needed — `status: str = ""` default is compatible with existing MongoDB documents (`extra="allow"` + Pydantic handles unknown fields gracefully).
2. Deploy widget (Vercel): **no change required** — widget already preserves partial content in the bubble and shows the banner on `done{failed}`.
3. Deploy dashboard (Vercel): **no change required** — conversation status is role-based and already switches to "answered" once the assistant row exists.
4. Monitor Railway logs for new `rag_partial_answer_persisted` and `rag_partial_answer_persist_failed` warning lines.

---

## F — What the widget saw (and will still see)

| SSE frame | Content                                                          |
| --------- | ---------------------------------------------------------------- |
| `sources` | `[{citation: 1, url: "...", title: "Indira University"}, ...]`   |
| `message` | `{"delta": "Indira University provides"}`                        |
| `error`   | `{"code": "GENERATION_FAILED", "message": "Generation failed."}` |
| `done`    | `{"status": "failed", "finish_reason": "", ...}`                 |

Widget behavior (unchanged): partial content rendered in the bubble + "Learn more" source card → temporary unavailable banner + Retry/Dismiss. **After the fix, retrying produces a fresh assistant row** (no duplication of the partial).

---

## G — Dashboard behavior (before / after)

|                     | Before                                  | After                                               |
| ------------------- | --------------------------------------- | --------------------------------------------------- |
| Conversation status | **"Awaiting reply"** (last role = user) | **"Answered"** (last role = assistant)              |
| Messages shown      | User only                               | User + partial assistant + sources                  |
| Detail page         | User bubble only                        | User bubble + partial assistant bubble with sources |

No dashboard code change. The fix is entirely backend-side — persisting the missing assistant row.

---

## H — Regression coverage (new tests)

| Test                                                               | Failure class                           | What is asserted                                                                                  |
| ------------------------------------------------------------------ | --------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `test_failure_before_first_delta_persists_nothing_partial`         | Pre-first-delta `GenerationError`       | 0 assistant rows, no `status` marker                                                              |
| `test_failure_after_one_delta_persists_partial_answer`             | Mid-stream after 1 delta                | content == delta, `status="failed"`, `finish_reason=""`, `truncated=False`, tokens=0, usage empty |
| `test_failure_after_multiple_deltas_persists_full_partial_content` | Mid-stream after 3 deltas               | content == full concatenation, no content lost                                                    |
| `test_normal_stop_unchanged_and_not_marked_failed`                 | Successful `STOP`                       | `status=""`, `finish_reason="STOP"`                                                               |
| `test_max_tokens_truncation_unchanged_no_duplicate_record`         | `MAX_TOKENS` truncation                 | `truncated=True`, `status=""`, exactly 1 assistant row                                            |
| `test_partial_failure_leaves_dashboard_conversation_not_awaiting`  | Mid-stream + `ConversationService`      | `detail.status == "answered"`                                                                     |
| `test_partial_persist_failure_does_not_mask_generation_failure`    | Messages repo fails on assistant create | SSE `error` still emitted with `GENERATION_FAILED`                                                |
| `test_retry_creates_fresh_generation_without_duplicating_partial`  | Retry after partial failure             | Old partial untouched (`status=failed`), new successful row with `status=""`                      |

---

## I — Schema migration needed

**None.** The new `status: str = ""` field on `ChatMessage` is additive:

- `model_config = ConfigDict(extra="allow")` means existing MongoDB documents without the field round-trip cleanly through `from_doc()` (Pydantic treats absent optional fields as their default).
- No MongoDB migration, no Alembic change, no API version bump.
- The field is ignored by all existing consumers until the dashboard is updated to render it (optional follow-up).

---

## J — Known limitations

1. Exact provider failure subtype not identifiable without Railway production logs.
2. Token counts for failed partial turns are zero (unreported by provider on mid-stream exception); cannot retroactively recover them.
3. The `status` field on `ChatMessage` is not yet surfaced through the dashboard API; the dashboard cannot visually distinguish "answered-complete" from "answered-failed". Exposing this is an optional follow-up.
4. Session `last_activity` is bumped on partial persistence (behavioral change from previous no-touch failure); affects conversation list ordering.

---

## K — What would need to be committed (when ready)

Three files only, no new files, no `git reset --hard`, no force push:

```
backend/models/chat_message.py       (+13 lines)
backend/services/chat/rag_service.py (+81 lines)
tests/test_rag_service.py            (+271 lines)
```

**Commit message suggestion:**

```
fix: persist partial assistant answer on mid-stream generation failure

When generation fails after one or more assistant deltas were streamed
to the widget, the partial reply is now persisted as a ChatMessage with
status="failed". This prevents the conversation from staying stuck in
"awaiting reply" on the dashboard, while the SSE error + terminal
done{status:"failed"} frame still surfaces the failure truthfully.

- Added status: str = "" field to ChatMessage ("" success, "failed" mid-stream error)
- Added _persist_partial_answer() best-effort helper in RagService
- Wired into stream_answer generation exception handler (guard: deltas non-empty)
- Added 8 regression tests covering all constraint scenarios
- Full suite green: 2489 passed, 90% coverage, ruff clean, mypy backend clean
```
