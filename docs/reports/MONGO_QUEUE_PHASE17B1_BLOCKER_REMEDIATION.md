# Phase 17B.1 — Email Delivery Identity and Document Stale-Write Remediation

- **Date:** 2026-09-26
- **Branch / HEAD:** `main` @ `d63deff318ef62c45f14d3ebc83b082e96ecf158` (unchanged — nothing committed, nothing pushed)
- **Scope:** correctness remediation for the two blockers Phase 17B left open. **No cutover, no default change, no production traffic, no deploy.**
- **Predecessors:** Phase 17B shadow validation (`docs/reports/MONGO_QUEUE_PHASE17B_SHADOW_VALIDATION_REPORT.md`), FIND-03 remediation (`docs/reports/FIND03_CRAWL_RESURRECTION_REMEDIATION.md`), Phase 16 email design (`docs/reports/MONGO_QUEUE_PRODUCTION_READINESS.md`)

Every measurement is labelled **[MEASURED]**, **[VERIFIED]**, **[CALCULATED]**,
**[INFERRED]** or **[NOT MEASURED]**. Readiness cells are `PASS` / `PARTIAL` / `FAIL` /
`NOT MEASURED`.

---

## 1. Verdict

> **PHASE 17B.1 PASS — BLOCKERS RESOLVED**
>
> Scoped strictly to the two correctness blockers Phase 17B left open. This authorizes
> **no** deployment, cutover, or default change (§17, §26).

**PASS** on both blockers, with two explicitly unresolved residual cases (§20).

Both Phase 17B blockers are closed and each fix is proven load-bearing by falsification
(§22): reverting any one of the five new mechanisms makes the new tests fail, so the
suite measures the fix rather than the absence of a symptom.

- **Blocker A** (content-derived mail idempotency key) is replaced by a per-delivery
  identity plus a durable delivery-state machine. A legitimate repeat send is never
  suppressed; a delivery already recorded as accepted is never sent again; an
  indeterminate outcome is recorded as *unknown* and escalated rather than blindly
  re-sent.
- **Blocker B** (unfenced document knowledge writes) is replaced by a single atomic
  compare-and-set that touches knowledge fields only. A stale execution can no longer
  rewind `knowledge_checksum`, `knowledge_status`, or the source `content`/`checksum`.

Production is still **not** cut over, and this report does not recommend it. This phase
removed correctness defects; it did not exercise cutover (§17).

---

## 2. Environment

| Item | Value | Label |
|---|---|---|
| HEAD before / after | `d63deff318ef62c45f14d3ebc83b082e96ecf158` | VERIFIED (identical) |
| Branch | `main` | VERIFIED |
| Python | 3.13.14 | MEASURED |
| MongoDB | isolated prototype `mongod` (real, not simulated) | MEASURED |
| Resend SDK | installed; `Emails.SendOptions.idempotency_key` present | VERIFIED |
| Full suite | `3326 passed, 13 skipped, 3 warnings` in 268.39 s | MEASURED |
| Queue + prototypes + harness | `606 passed, 1 skipped` in 96.67 s (best of 3, §15) | MEASURED |

No `.env.production` was read. No provider, embedding, or crawl network call was made.

---

## 3. Email audit — the full delivery lifecycle, traced before any change

Nothing was edited until this map existed, because both plausible fixes (a different
key formula, and a durable marker) change what the *worker* must know.

```
service (auth)          enqueue_email                       ARQ              send_email
  │ tenant_id, body         │ delivery_id = uuid4()            │                   │
  │                         │ key = email:<tenant>:<id>       │                   │
  ├────────────────────────►│ payload {…, delivery_id, key}   │                   │
  │                         ├───────────────────────────────► │ ────────────────► │
  │                         │   (Redis / queue row)           │   claim delivery  │
  │                         │                                 │   state=sending   │
  │                         │                                 │   ──► provider ───┼──► mailbox
  │                         │                                 │        │          │
  │                         │                                 │   accepted/failed/│
  │                         │                                 │        unknown    │
```

Facts established from the code **[VERIFIED]**:

| Question | Answer |
|---|---|
| Is the queue job ID stable across reclaim? | Yes for a Mongo row, and ARQ retries reuse the job ID — but neither reaches the worker. |
| Does `send_email` receive a job ID? | No. `backend/workers/jobs/email.py:317` calls `_arq_redis().enqueue_job("send_email", …)` directly. |
| Could the job ID be used as the key? | No, not reliably: only the Mongo backend guarantees it, and this path does not expose it. A delivery identity minted at enqueue is backend-independent. |
| Was the current key safe? | **No.** `sha256(tenant, to, subject, text, html)` — two different logical deliveries of identical content share one key. |
| Why did this not fire in production? | The three auth flows embed a fresh JWT `jti` in each body, so content happened to differ each time. That is an accident, not a property. |
| Are the auth flows tenant-scoped? | Yes for all three. A tenant-less email is representable (public `forgot_password`). |
| Did a durable outbox/marker exist? | **No.** Nothing recorded whether a send had happened. |

The bypass is not an oversight unique to mail: `crawl.py` uses the `WorkerQueue` protocol
(`backend/queue/protocol.py:102`) for its knowledge child (`crawl.py:154`,
`await queue.enqueue(...)`) but reaches for raw ARQ on its own path
(`crawl.py:127`). Both patterns exist in the codebase today **[VERIFIED]**. Mail only
ever had the raw-ARQ one, which is precisely why the job ID was never an option for it.

---

## 4. The defect, reproduced end to end

**VERIFIED** by test, through the real `AuthService`, the real `enqueue_email` and the
real `send_email` — only the ARQ enqueue call and the SDK's network call are faked:

`test_a_user_asking_twice_for_a_reset_receives_two_emails`

A user calling `forgot_password` twice received **one** email under the Phase 17B key,
because both rendered messages hashed to one key and the provider treated the second as
a duplicate. With the `jti` removed from the equation (which is what any fixed-body
template would do) the production behaviour is identical.

The counterweight is asserted too:
`test_one_password_reset_redelivered_twice_is_still_one_email` — one request delivered
three times is **one** email. Two requests are two deliveries; one request is one
delivery. These are different guarantees and both are tested.

---

## 5. Fix A1 — the provider key is derived from a delivery identity

`backend/queue/mail_idempotency.py`, `backend/workers/jobs/email.py`

A `delivery_id` (uuid4 hex) is minted **once per enqueue** and persisted in the job
payload. The key becomes `email:<tenant>:<delivery_id>`, still length-checked against
Resend's 256-character maximum.

Properties, each **[VERIFIED]** by a named test:

| Property | Test |
|---|---|
| One delivery ⇒ one key, forever | `test_one_delivery_always_produces_the_same_key` |
| Two enqueues ⇒ two keys | `test_two_enqueues_are_two_deliveries_with_two_keys` |
| Content cannot influence the key | `test_content_cannot_influence_the_key` (4 fields) |
| Identical content does not collide | `test_identical_content_does_not_collide` |
| Tenant-scoped | `test_the_key_is_tenant_scoped` |
| Tenant-less mail is still protected | `test_a_tenant_less_message_is_still_protected` |
| Long tenant fails loudly, never truncates | `test_a_very_long_tenant_fails_loudly_rather_than_being_truncated` |
| No recipient/body/subject in the key | `test_the_key_contains_no_secret_material` |

The minting site is deliberate and unchanged in spirit from 17B: the enqueue site is the
only place that has the authoritative tenant, and fixing the identity in the payload
means every retry and reclaim reuses it *by construction* rather than by recomputation.

The legacy content key is retained, unused by any production path, so the falsification
tests can still build it and demonstrate what it did.

---

## 6. Fix A2 — durable delivery state (the part that was missing entirely)

New file `backend/repositories/email_delivery_repository.py`; collection
`email_deliveries`; `_id` is the `delivery_id`, so uniqueness is structural.

```
(absent) ──claim──► sending ──accept──► accepted   (TERMINAL)
                      │            └─unknown─► unknown ──┐
                      └─fail──────────────────────────► failed
                                                       │
accepted / failed / unknown ──claim──► sending  (re-attempt, time-gated)
```

| State | Meaning | Re-send allowed? |
|---|---|---|
| `pending` | never attempted | yes |
| `sending` | an attempt holds it | only once the attempt is stale |
| `accepted` | provider confirmed; message id stored | **never** |
| `failed` | definitive rejection; nothing sent | yes |
| `unknown` | provider's answer was lost | only inside the provider window |

Three properties make this honest rather than merely deduplicating:

1. **A delivered email is never re-sent.** The provider is not even consulted, so the
   guarantee does not depend on Resend's 24 h window. *(`test_a_known_accepted_delivery_is_never_sent_again`)*
2. **An unknown outcome is recorded as unknown**, not as sent and not as failed.
   Recording it as `failed` would invite a duplicate; recording it as `accepted` would be
   a lie. *(`test_a_lost_response_is_recorded_as_unknown_not_as_sent`)*
3. **Past the provider window, the record escalates instead of re-sending.**
   *(`test_an_unknown_delivery_is_never_resent_after_the_window`)*

Concurrency is fenced by `attempt_token`: a stalled execution whose lease was taken over
cannot overwrite the winner's outcome. *(`test_a_slow_execution_cannot_overwrite_the_winning_outcome`)*

A crashed attempt is recoverable: once `mail_delivery_attempt_stale_seconds` (120 s)
elapses, the next execution takes it over with the same key.
*(`test_a_crashed_attempt_is_taken_over_by_the_next_execution`)*

### Crash matrix — every point the worker can die, and what the next execution does

This is the property Phase 17B said the design lacked, so it is worth stating
exhaustively rather than by assertion. "Next execution" means any later delivery of the
same queue job, which is at-least-once and therefore expected.

| # | Worker dies… | Durable state left behind | Next execution | Duplicate risk |
|---|---|---|---|---|
| 1 | before the claim | row absent | claims, creates row, sends | none — nothing was sent |
| 2 | after claim, before calling the provider | `sending`, fresh | sees `sending` inside the stale window ⇒ **refused, `inflight`**; after 120 s ⇒ takes over, same key | none — the provider was never called |
| 3 | after the provider accepted, before the outcome write | `sending`, stale | after 120 s takes over and re-sends **the same key** ⇒ the provider collapses it | none **while the key window is open** |
| 4 | after the provider accepted, response lost (timeout) | `unknown` | inside the window ⇒ retry, same key, collapsed | none inside the window |
| 5 | after the provider **rejected** | `failed` | re-claims and re-sends | none — a rejection is a definite "nothing was sent" |
| 6 | after the outcome write | `accepted` | **refused, `accepted`** — the provider is not even called | none, ever |
| 7 | in case 3/4, but the key window has since closed | `sending`/`unknown`, stale | **refused, `unknown_expired`** ⇒ escalated, not re-sent | none — but the user may have no mail (§20) |

Rows 3/4 and row 7 are the same dilemma separated only by whether the provider would
still deduplicate. That is precisely why the window is anchored to the first attempt
(§12): a retry must not be able to renew it, or row 7 would silently become row 3 with a
dead provider guarantee.

Row 2's refusal is deliberate: within the stale window the previous execution may still
be alive, so the new one declines rather than racing it. The queue's own lease/heartbeat
(§16) is what eventually forces progress; the 120 s value is a backstop, not the primary
recovery mechanism.

Each row is covered. The pre-existing numbered case suite pins the provider-outcome
paths — `test_case_1_success`, `test_case_2_provider_rejects`,
`test_case_4_response_lost_after_the_provider_accepted`,
`test_case_5_worker_crashes_after_the_send`, `test_cases_6_and_7_lease_expires_during_the_provider_request`,
`test_case_8_retry_within_the_provider_window`,
`test_case_9_retry_after_the_provider_window_expired` — the state-machine tests pin rows 2
and 6, and the three window tests (`test_an_unknown_delivery_is_never_resent_after_the_window`,
`test_a_crashed_sending_attempt_past_the_key_window_escalates`,
`test_residual_duplicate_risk_beyond_the_provider_window`) pin row 7 **[VERIFIED]**.
Rows 1, 3 and 5 follow from the claim/outcome transitions in §6, which the case suite
above exercises directly.

---

## 7. Honest outcomes require the provider to classify its own failures

`backend/services/mail/providers.py`, `backend/services/mail/base.py`

`MailService.send` now returns `MailSendResult(provider_message_id)`, and the provider
raises `MailDeliveryIndeterminate` when the outcome is genuinely unknown. Only the
provider can make that call, so the provider makes it.

Classification is conservative, and it lives in `ResendProvider` — the only production
provider. Typed client-side errors and 4xx codes are **definite** rejections
(`_RESEND_DEFINITE_ERRORS`); timeouts, connection errors, 5xx and anything unrecognised
are re-raised as **indeterminate** *(`MailDeliveryIndeterminate`)*. Over-claiming a
definite failure is what would cause a duplicate send; under-claiming only costs a
delivery the same key safely deduplicates. *(`_is_definite_rejection`,
`test_a_definite_rejection_is_not_reported_as_indeterminate`,
`test_a_lost_response_is_reported_as_indeterminate`)*

**Scope of that claim, stated precisely so it is not over-read:** `MailpitProvider` does
*not* classify. It uses `urllib` and propagates whatever happens — a 4xx becomes a
`RuntimeError`, a timeout or refused connection becomes `URLError`/`TimeoutError` — and
the worker records any non-`MailDeliveryIndeterminate` exception as a definite `failed`
(§6). So a Mailpit timeout is recorded as a rejection when the outcome was in fact
unknown. This is **left as-is deliberately**: Mailpit is development-only, nothing in
production resolves to it, and it has no idempotency support at all, so "escalate
instead of retry" would not prevent a duplicate there either. Teaching it to raise
`MailDeliveryIndeterminate` would be a behaviour change to the dev provider outside the
two blockers, and it is recorded as a judgement call instead (§21).

`MailpitProvider` returns `provider_message_id=None`. That is honest — it parses no id —
rather than a placeholder that would make the record claim more than is known.

---

## 8. What the delivery record deliberately does not store

**VERIFIED** by `test_the_delivery_record_holds_no_recipient_or_body`.

Stored: `delivery_id`, `state`, `tenant_id`, `provider_key`, provider message id, attempt
count/token, timestamps, key-expiry deadline, a one-way error-type hash.

Not stored: recipient address, subject, body. `content_hash` is a sha256 fingerprint kept
for debugging ("were these two attempts the same message?"), so the collection can be
retained and inspected without becoming a new home for customer mail.

Indexes are registered with the app's existing bootstrap
(`backend/core/database.py` → `init_indexes`): `tenant_id`, plus a partial index on
`(state, last_attempt_at)` for the ops query "deliveries that never reached a terminal
state". `_id` is unique by default.

---

## 9. Document audit — every write that can change knowledge state

All `upsert()` call sites were enumerated before editing
**[VERIFIED]**:

| Location | Kind | Action |
|---|---|---|
| `processor.py:249` (PROCESSING marker) | knowledge write | → CAS |
| `processor.py:447` → `_record_document` (READY) | knowledge write | → CAS |
| `processor.py:670` (`_record_failure`) | knowledge write | → CAS |
| `knowledge_service.py` (2 sites) | **ingestion** — writes the full document | left as `upsert` |
| `crawler.py` | **ingestion** — writes the full document | left as `upsert` |

All three knowledge writes converge on a single helper, `_record_knowledge`
(`processor.py:620`), which performs the one `update_knowledge_if_current` call
(`processor.py:626`) **[VERIFIED]**. There is exactly one CAS call site to reason about,
not three.

The ingestion sites legitimately write the whole document; restricting them would break
incremental crawl. Only the three knowledge writes read a document earlier and write it
back later, and those are the only ones that can rewind state.

`update_payload()` is `document.to_doc()` minus `_id`, i.e. the **entire** document
including `content` and `checksum` **[VERIFIED]**. So the hazard was wider than 17B
reported: a stale knowledge write could also restore old source content.

---

## 10. Fix B — one atomic compare-and-set, knowledge fields only

`backend/repositories/document_repository.py`, `backend/services/knowledge/processor.py`

`DocumentRepository.update_knowledge_if_current(document, *, expected_checksum) -> bool`
performs **one** `update_one` whose filter carries both preconditions. There is no
read-then-write anywhere, so there is no TOCTOU window.

Guard 1 — **source identity**: `checksum == expected_checksum`. If the page was re-crawled
underneath, the pass is refused: embedding old content and stamping its checksum onto new
content is wrong twice over (the dashboard would claim Y was embedded, and the checksum
gate would then suppress the pass that actually needs to run).

Guard 2 — **knowledge-state monotonicity**: a *non-ready* write is refused when the row
already records a completed embed **of this same source** (`$nor` on
`{knowledge_status: ready, knowledge_checksum: expected_checksum}`). Without it, a slow
failure record could mark a document `failed` while its chunks sat in the vector store.

A *ready* write is exempt from guard 2 on purpose: re-recording the same success is
idempotent and must stay allowed so it can repair bookkeeping such as a chunk count reset
out of band. *(`test_a_stale_failure_record_cannot_overwrite_a_completed_embed`)*

Structural defence: the applied `$set` is restricted to a closed
`KNOWLEDGE_WRITE_FIELDS` allowlist, so a knowledge write is *incapable* of rewriting
`content`, `checksum` or `title` even if the guard were bypassed.
*(`test_knowledge_payload_cannot_carry_source_fields`)*

---

## 11. Document regressions

| Test | What it pins |
|---|---|
| `test_a_stale_document_write_cannot_rewind_the_document` | the core Blocker B guarantee |
| `test_a_stale_knowledge_write_cannot_rewind_the_source_content` | a knowledge write never rewrites the source |
| `test_a_stale_failure_record_cannot_overwrite_a_completed_embed` | failure cannot demote a success |
| `test_interleaved_dual_execution_never_rewinds_state` | **100 parametrized interleavings**, fake |
| `test_a_knowledge_write_is_refused_after_the_source_changes` | re-crawl during processing |
| `test_a_knowledge_write_never_crosses_tenants` | two tenants, independently fenced |
| `test_mongo_cas_*` (6 tests, incl. 100 parametrized) | the same guarantees on real Mongo |

**The re-crawl path has two halves, and only fixing one would be a different bug.** A
changed checksum must (a) let the *new* version be processed, and (b) stop the *old*
attempt from undoing it:

| Half | Test | What it pins |
|---|---|---|
| (a) Y remains processable | `test_a_changed_checksum_is_processed_and_replaces_the_old_chunks` | X embedded → document re-crawled to Y, with `knowledge_checksum` deliberately left stale at X → the Y pass runs, `knowledge_checksum` ends at Y, and the stale X chunks are *replaced*, not duplicated. A fix that refused Y as well would look safe and would silently stop re-processing changed pages. |
| (b) stale X cannot roll Y back | `test_a_stale_x_attempt_cannot_roll_y_back` | a late attempt still carrying X is refused, so Y's state and chunks survive |

Both run end-to-end through `process_document`, not just against the repository, and both
pass **[VERIFIED]**.

The 100-iteration tests are **parametrized, not looped**, so a failure names the exact
ordering that broke. Across all 100 interleavings the losing writer was refused
**every single time and 0 stale writes were accepted** — the assertion is on the
resulting row, not merely on the return value, so a write that slipped through and
then repaired itself would still fail the test
*(`test_interleaved_dual_execution_never_rewinds_state`, and the real-Mongo equivalent
`test_mongo_cas_converges_under_100_interleavings`)* **[MEASURED]**.

A cross-tenant test only means something if the two rows are addressed the same way;
both tenant tests therefore seed two tenants sharing `website_id` + `url`, which is the
case where a filter missing `tenant_id` would hit the wrong row.

`matched_count == 0` is returned as `False`, and callers treat it as a normal
`"superseded"` outcome — not an error. `process_document` returns
`{"status": "superseded"}` when the completion write is refused, so the queue's completion
reflects what was actually recorded.

---

## 12. A defect in the first implementation of this fix, found by testing against a real database

The email state machine was initially verified **only** against
`FakeEmailDeliveryRepository`. Writing the same guarantees against a real `mongod`
immediately produced **8 failures**, and the first of them was severe.

**The claim was not scoped to its delivery.** `MongoEmailDeliveryRepository._claim_filter`
matched on *state* alone:

```python
return {"$or": [{"state": {"$in": ["pending", "failed"]}}, …]}
```

`_id` was absent, so `find_one_and_update` matched **any** row in the collection in a
retryable state. Consequences, all reproduced on the database:

- a never-attempted delivery could claim, and mutate, a *different* delivery's row;
- a redelivery of an already-**accepted** delivery could consume an unrelated `failed`
  row — the mail then goes out a second time while the accepted row still reads
  accepted, which is the precise failure the durable store exists to prevent;
- concurrent claims of one delivery could each take a different row, so both would send.

The method's own docstring claimed "`delivery_id` is in the filter (not just the
update)". It was not. The comment described the intended invariant rather than the
code, which is exactly the kind of drift a test has to catch.

**Why the fake could never have found it.** `FakeEmailDeliveryRepository` keeps records
in a dict keyed by `delivery_id`, so a lookup cannot wander onto another delivery's row.
The defect class is *invisible by construction* in the fake — and the fake's docstring
claimed it "mirrors the Mongo CAS exactly". It did not, and now says precisely what it
cannot check and why the database-level tests are not optional.

Three further defects surfaced the same way:

| Defect | Consequence | Fix |
|---|---|---|
| `provider_key_expires_at` re-anchored to `now` on every claim | a repeatedly-retried `unknown` delivery pushes its own deadline out and is eventually re-sent **after the provider stopped honouring the key** — a real duplicate | deadline written once, at creation; the claim update does not restate it |
| a reclaim did not check the stored provider key | a payload claiming an existing delivery id with a *different* key could re-point a real delivery at a different send | key equality added to the claim filter; a mismatch is refused |
| a stale `sending` row was reclaimable past the key window | a worker that died *after* the provider accepted could be taken over once the provider stopped deduplicating — a real second send | the takeover now requires an open window, and otherwise escalates exactly like `unknown` |

The last one is a genuine design hole rather than an implementation slip, and the test
that caught it is the reason it is worth stating: `sending` and `unknown` are the same
unknowable outcome reached by two different routes (the provider's answer was lost; the
worker died without reporting), so both must escalate together once the window closes.

**The lesson, recorded because it is the transferable part:** the fix passed 48/48
against a fake and would have shipped. It took a real database to find a one-field
omission with a severe failure mode. A fake can only ever assert the conditions it was
written to share; the query is where a claim becomes scoped, and a dict lookup has no
query to get wrong.

Also corrected in the same pass: `_to_record` now normalises a stored state through
`cast_state`, so a row written by a buggy or future version cannot surface a state this
class cannot reason about (an unrecognised value would otherwise read as "not terminal"
and invite a resend).

---

## 13. Fake / Mongo parity

`tests/fakes.py::FakeDocumentRepository.update_knowledge_if_current` and
`FakeEmailDeliveryRepository` evaluate the same conditions as their Mongo counterparts.

The explicit constraint, and it is the one that matters: **the fake must not be stricter
than Mongo.** A fake that refused more than the database would make the durability
guarantees look better in the suite than in production. Both sides therefore evaluate the
same guards literally, and the Mongo tests exist precisely so the guarantee is measured
against the database rather than against the fake.

---

## 14. Full regression

| Gate | Command | Result | Label |
|---|---|---|---|
| Full suite | `pytest tests/ backend/` | **3326 passed, 13 skipped, 3 warnings**, 268.39 s | MEASURED |
| Queue + prototypes + harness | `pytest backend/queue/tests/ backend/prototypes/ tests/test_queue_shadow_validation_harness.py` | **606 passed, 1 skipped**, 96.67 s (best of the 3 runs in §15) | MEASURED |
| `check-backend.sh` | ruff + mypy + tests | **exit 0** — `2739 passed, 12 skipped, 3 warnings` in 144.15 s | MEASURED |
| ruff | `ruff check backend tests scripts` | All checks passed | MEASURED |
| mypy | `mypy backend` | Success, **no issues in 268 source files** | MEASURED |
| `check-input-validation.sh` | | **exit 1 — 21/22 passed**, 1 failed | MEASURED |

`pyproject.toml` sets `addopts = "-q"`, so a second `-q` on the command line makes it
`-qq` and pytest **omits the final count line** entirely. That produced a run whose
output looked like it had no results even though every selected test had passed; the
command lines in §25 deliberately do not add `-q` **[VERIFIED]**.

The single input-validation failure is the **pre-existing, unchanged** one:
`UsageMetricOut.metric not using MetricName Literal`. It is unrelated to this work and
was left alone per scope (§23).

Test counts, collected **[MEASURED]**; "before" values are sourced and labelled per row
because three of these files are untracked and have no `git` baseline:

| File | Before | After | Source of "before" |
|---|---|---|---|
| `tests/test_document_repository.py` | 2 | 109 | `git show HEAD:…` — VERIFIED |
| `backend/queue/tests/test_document_redelivery.py` | 15 | 117 | Phase 17B report §5 ("15 tests") |
| `backend/queue/tests/test_shadow_no_duplicate_side_effects.py` | 10 | 12 | Phase 17B report §9 ("10 tests") |
| `backend/queue/tests/test_email_idempotency_integration.py` | not recorded | 54 | no baseline published — **NOT MEASURED** |
| `tests/test_email_delivery_repository.py` | **0** | 13 | new file; the store had no database-level test at all |

---

## 15. Determinism — three consecutive identical runs

**[MEASURED]**, concurrency-sensitive selection
(`test_document_redelivery.py`, `test_document_repository.py`,
`test_email_idempotency_integration.py`, `test_ownership_races.py`,
`test_shadow_no_duplicate_side_effects.py`):

```
319 passed in 42.36 s
319 passed in 47.53 s
319 passed in 46.76 s
```

**[MEASURED]**, full queue + prototypes + harness, random ordering enabled:

```
606 passed, 1 skipped in 121.49 s
606 passed, 1 skipped in  96.67 s
606 passed, 1 skipped in 112.67 s
```

---

## 16. Phase 17B invariants re-verified

Every Phase 17B invariant is re-asserted by a named, still-green test. Nothing here was
re-implemented; this is a re-verification, and the test names are given so each row is
independently checkable **[VERIFIED]**:

| Phase 17B invariant | Test | Result |
|---|---|---|
| Child queue backend consistency (no split-brain) | `test_child_enqueue_split_brain.py` | PASS |
| Backend selection / unsafe config rejected | `test_backend_selection_and_config.py` | PASS |
| Heartbeat execution-version fencing | `test_ownership_races.py` | PASS |
| Stale **complete** = 0 (cannot revive a job) | `test_ownership_races.py` | PASS |
| Stale **fail** = 0 (cannot kill a newer attempt) | `test_ownership_races.py` | PASS |
| Stale **renew** = 0 (cannot extend a lease it lost) | `test_a_stale_execution_cannot_renew_after_a_same_worker_reclaim` | PASS |
| FIND-03 terminal monotonicity (exactly one crawl winner) | `test_exactly_one_crawl_terminal_winner_under_dual_execution` | PASS |
| WK-01 winner-only purge | `test_wk01_a_losing_worker_never_purges_the_winners_documents`, `test_wk01_the_purge_helper_is_invoked_exactly_once` | PASS |
| Shadow executes nothing (no side effects) | `test_shadow.py`, `test_shadow_no_duplicate_side_effects.py` | PASS |
| Mismatch detection is observable, never silent | `test_a_mismatch_is_observable_and_never_silent`, `test_a_reported_mismatch_does_not_leak_payload_values` | PASS |
| Envelope parity / parity sweep | `test_envelope_parity.py::test_parity_sweep_reports_no_unexplained_mismatch` | PASS |
| **ARQ remains the default** backend | `test_arq_is_the_default_when_queue_backend_is_absent`, `test_default_backend_is_arq` | PASS |
| **Mongo remains explicit opt-in** | `test_mongo_opt_in_selects_the_mongo_adapter`, `test_mongo_backend_requires_explicit_enable`, `test_production_mongo_requires_an_explicit_database` | PASS |
| Non-queue Redis consumers preserved | `test_shadow.py` | PASS |
| FIND-03 crawl resurrection | `test_find03_crawl_resurrection.py` | PASS |

`scripts/queue_shadow_validation.py` **[MEASURED]**:

```
jobs mirrored   : 5
jobs executed   : none
no side effects : True
send_email      True   (match)
VERDICT: PASS - no unexplained differences
```

---

## 17. No cutover

No default was changed, no Mongo queue was enabled, no ARQ/Redis consumer was removed, no
`.env.production` was touched, and nothing was deployed to Railway or Vercel. There is
**no cutover recommendation** in this report.

---

## 18. Forensic review of the dirty tree

**[VERIFIED]** — HEAD is `d63deff318ef62c45f14d3ebc83b082e96ecf158`, unchanged from the
Phase 17B baseline. No `git reset`, `clean`, `restore`, `checkout`, `stash`, commit, push
or force-push was performed. Nothing was deleted.

All 13 pre-existing modified files and all 7 untracked paths are still present. This
phase added changes on top.

The final tree measures **27 changed paths: 18 modified tracked + 9 untracked**, against
the 13 + 7 baseline — i.e. this phase newly modified 5 tracked files and added 2 new
untracked files. `git diff --stat` totals **18 files changed, 1679 insertions(+),
111 deletions(-)** for the tracked set, and `git diff --check` exits **0** (no trailing
whitespace, no conflict markers). Both are re-run at the end of this phase, not
inherited from earlier work **[MEASURED]**.

Comparing against the Phase 17B baseline (§17 of that report) rather than against
`HEAD`, the 5 tracked files that enumeration does **not** already list as dirty are the
ones this phase newly dirtied: `backend/repositories/document_repository.py`,
`backend/services/knowledge/processor.py`, `backend/core/database.py`,
`backend/services/mail/__init__.py`, `tests/test_document_repository.py`. The other
tracked paths in the table below were *already* modified at the baseline and were
extended, so a reader diffing against `HEAD` alone would over-count this phase's
contribution. Per-file attribution here rests on the baseline report's enumeration, not
on an independent snapshot — the totals above are the directly measured part.

Untracked directories (`backend/queue/`, `backend/prototypes/`, `docs/reports/`) are
reported as single paths by `git status`, so edits to files inside them — including the
six `backend/queue/` paths below — do not appear in `git diff --stat` at all. That is
why the table below is the authoritative inventory and `git diff` alone is not.

| Path | Nature |
|---|---|
| `backend/repositories/email_delivery_repository.py` | **new** — durable delivery state |
| `backend/repositories/document_repository.py` | CAS method, filters, allowlist |
| `backend/services/knowledge/processor.py` | 3 writes → CAS; `superseded` result |
| `backend/services/mail/base.py` | `delivery_id`, `MailSendResult`, `MailDeliveryIndeterminate` |
| `backend/services/mail/providers.py` | return result; classify outcome |
| `backend/services/mail/__init__.py` | exports |
| `backend/workers/jobs/email.py` | identity minting + state machine |
| `backend/queue/mail_idempotency.py` | delivery key; content key demoted to legacy |
| `backend/queue/registry.py` | optional delivery-field validation |
| `backend/core/config.py` | two new settings (defaults only, no behavior switch) |
| `backend/core/database.py` | delivery-store index registration |
| `tests/fakes.py` | CAS fake + `FakeEmailDeliveryRepository` (+ the §12 parity fix) |
| `tests/test_document_repository.py` | Mongo CAS parity |
| `tests/test_email_delivery_repository.py` | **new** — 13 database-level tests for the delivery store |
| `backend/queue/tests/test_registry.py` | delivery-field and legacy-payload validation |
| `backend/queue/tests/test_document_redelivery.py` | stale-write regressions |
| `backend/queue/tests/test_email_idempotency_integration.py` | rewritten for new semantics |
| `backend/queue/tests/test_shadow_no_duplicate_side_effects.py` | shadow delivery-state safety |

`backend/prototypes/mongo_queue/email_idempotency.py` deliberately still contains the
Phase 16 content-key helper. It is a frozen prototype used for benchmark comparison;
changing it would alter the artifact Phase 16 measured.

---

## 19. Privacy and logging

**[VERIFIED]** by assertion in the new tests:

- the delivery record contains no recipient, subject or body;
- the provider never logs the body; recipients are logged only via `mask_email`, the
  subject only as `content_hash` **[VERIFIED]** in `backend/services/mail/providers.py`;
- the key embeds a raw tenant id, so it is never logged raw.
  `redact_secret_key` (`backend/core/privacy.py:51`) splits on the last colon and emits
  `email:<redacted>:…<last 8 of delivery id>`, so the tenant segment is replaced while
  the namespace and a short delivery-id tail survive for correlation
  **[VERIFIED]**, covered by `test_the_key_contains_no_secret_material`;
- the worker's failure log masks the recipient and hashes the subject
  (`_log_failure`, `backend/workers/jobs/email.py:244`), and the accepted/unknown and
  other refusal lines go through `_log_refusal` (`:265`, logging at `:272`), which masks
  the recipient and hashes the subject the same way **[VERIFIED]**;
- a recorded error is a hash of the error **type** only
  (`content_hash(type(exc).__name__)`, `backend/workers/jobs/email.py:228`), because a
  provider exception message can embed the request;
- `tenant_id` now rides in the queue payload so the delivery record is filed under the
  real tenant. It is an internal ownership field, not customer content, and the payload
  already carries the recipient and body — so this adds no exposure, while its absence
  made every real record read `tenant-unknown` and the tenant index useless.

A payload enqueued before this change (no `delivery_id`) is sent the pre-17B way and
logged as `email_delivery_untracked`, rather than being given an invented identity that
could collide with a real delivery. `backend/queue/registry.py` **accepts** that shape
rather than rejecting it — see §21(1) for why the two layers had to agree.

---

## 20. Residual risk — stated, not hidden

**NOT MEASURED / unresolvable in application code.** An `unknown` delivery whose provider
idempotency window has since elapsed. The provider accepted the send and never said so;
nothing in our database can prove whether the user has the mail. It is now **escalated**
(`email_delivery_escalated`) rather than re-sent, which is the honest resolution — the
duplicate is avoided, but the case needs a human. *(`test_residual_duplicate_risk_beyond_the_provider_window`)*

Also open, and unchanged by this phase:

- An `unknown` delivery that is never retried is a *silent* non-delivery from the user's
  point of view. The log line is the only signal. **[INFERRED]** — an alerting rule on
  `email_delivery_escalated` would close this and is not built here (out of scope, §23).
- Two *different* delivery identities for one user action are possible if an enqueue
  site is invoked twice (e.g. a double-clicked form). Each is a legitimate delivery, so
  each sends. This is correct per-delivery behaviour; rate limiting is not part of this
  phase. **[INFERRED]**
- A provider that honours keys for a shorter window than 24 h would widen §20's window.
  The value is configurable (`mail_provider_idempotency_window_seconds`) rather than
  hard-coded. **[INFERRED]**

A second residual case, **new in this phase and created by fixing the first**:

- The §12 fix means a crashed attempt can no longer be taken over once the provider's
  key window has closed — it escalates instead. That is the correct trade (a takeover
  then would be a real duplicate), but it converts a recoverable situation into an
  escalation whenever a delivery sits in `sending` for longer than 24 h. Reachable only
  if no execution retries it for a full window, e.g. the queue is down or the job is
  re-queued much later. **[INFERRED]**, not measured. The alternative — re-sending and
  risking a duplicate — was rejected deliberately.

---

## 21. Three judgement calls worth flagging for review

All are places where a defensible alternative exists, so they are recorded rather than
buried:

1. **A legacy payload with a key but no `delivery_id` is now accepted, not rejected.**
   The registry previously refused it; the worker had an explicit fallback for it. The
   two contradicted each other, and refusing would silently drop mail already queued by
   the previous release. The registry now accepts it and the worker sends it the pre-17B
   way, keeping the key it already carried and logging `email_delivery_untracked`. The
   cost is that such a send has no durable row — which is what the warning is for.
2. **A `sending` row past the key window escalates** (§20). The alternative is to resend
   on the grounds that the crashed attempt probably never reached the provider. That
   reasoning is unverifiable, and being wrong costs a customer a duplicate email, so the
   conservative branch was taken.
3. **`MailpitProvider` does not classify its failures** (§7). A Mailpit timeout is
   recorded as a definite `failed` rather than `unknown`, which is imprecise. The
   alternative — mapping Mailpit timeouts and connection errors to
   `MailDeliveryIndeterminate` — was not taken because Mailpit is development-only and
   supports no idempotency, so escalating buys no duplicate protection there while
   changing the dev provider's behaviour outside the two blockers under repair. The
   honest consequence: **indeterminate detection is claimed for Resend, not for every
   provider.**

---

## 22. Falsification — do the tests actually measure the fix?

This is the part that distinguishes a fix from a plausible-looking diff. Each mechanism
was disabled at runtime, **in isolation**, and only the test file that owns that
mechanism was re-run, so each number is attributable to exactly one mechanism.

| Reverted to | Scoped to | Result | Label |
|---|---|---|---|
| Document CAS → unconditional `upsert` (Phase 17B) | `test_document_redelivery.py` + `test_document_repository.py` | **104 failed**, 122 passed | MEASURED |
| Key → content-derived (Phase 17A/17B) | `test_email_idempotency_integration.py` | **2 failed**, 52 passed | MEASURED |
| Delivery store → always grants a claim (no durable state) | `test_email_idempotency_integration.py` | **25 failed**, 29 passed | MEASURED |
| Claim filter → unscoped by `_id` and by key (§12) | `test_email_delivery_repository.py` | **4 failed**, 9 passed | MEASURED |
| Key window → re-anchored per claim, takeover ungated | `test_email_delivery_repository.py` | **2 failed**, 11 passed | MEASURED |

Reading the rows:

- The document row's 104 failures are the 100 parametrized interleavings plus the 4
  targeted stale-write regressions. The 122 passes include the **real-Mongo** CAS tests,
  which correctly stayed green: the revert patched the fake, not the database. That is
  the intended relationship (§13) and it is why the Mongo tests exist.
- The key row's 2 failures are the two end-to-end auth tests, i.e. exactly the
  legitimate-mail-suppression defect (§4). The other 52 pass because with the durable
  store intact a redelivery is still deduplicated — the key and the store each catch a
  different failure, which is why both exist.
- The store row's 25 failures are the state-machine tests. Note this experiment **failed
  to detect anything on the first attempt** (48/48 passed): the test's own fixture had
  re-patched the store after the harness did. Re-running against the repository *class*
  produced the real result. Recorded because "the suite passed" and "the suite cannot
  detect the regression" are very different claims, and only one of them is evidence.
- The last two rows are the §12 defects, each reverted on its own. The scoping row fails
  the hijack, the accepted-redelivery, and both identity-mismatch tests. The window row
  fails exactly the two window tests and nothing else — the narrow, attributable result
  one wants, and the reason the harness was rewritten: an earlier version of that
  experiment broke all 13 tests, which would have been evidence of nothing except a bug
  in the experiment.

---

## 23. Explicitly out of scope

Not done, deliberately: queue cutover or default change; ARQ/Redis consumer removal;
Mongo queue enablement; any deploy; `.env.production`; real provider/embedding/crawl
calls; the pre-existing `UsageMetricOut.metric` input-validation failure; alerting or
dashboards for `unknown`/`escalated` deliveries; TTL/retention for
`email_deliveries` (the collection is currently unbounded — **[INFERRED]** it should get
one, and it was not added here to avoid choosing a retention policy inside a correctness
fix); refactoring the Phase 16 prototype.

---

## 24. Readiness matrix

| Area | Cell | Evidence |
|---|---|---|
| Email: per-delivery identity | **PASS** | §5, 8 key tests |
| Email: legitimate repeat not suppressed | **PASS** | §4, `..._twice_for_a_reset_...` |
| Email: accepted never re-sent | **PASS** | §6, `..._never_sent_again` |
| Email: unknown recorded honestly | **PASS** | §6, §7 — Resend |
| Email: indeterminate-outcome detection on **every** provider | **PARTIAL** | §7, §21(3) — Resend classifies; Mailpit does not (dev-only) |
| Email: window expiry escalates | **PASS** | §6, §20 |
| Email: concurrent attempts fenced | **PASS** | §6, attempt token |
| Email: crashed attempt recoverable **inside** the window | **PASS** | §6 |
| Email: claim scoped to one delivery (no hijack) | **PASS** | §12, real mongod |
| Email: reclaim requires a matching identity | **PASS** | §12, real mongod |
| Email: key window not renewable by a retry | **PASS** | §12, real mongod |
| Email: crashed attempt **past** the window escalates | **PASS** | §12 |
| Email: record filed under the real tenant | **PASS** | §19, `..._real_tenant` |
| Email: legacy payload still sendable | **PASS** | §21(1), `..._legacy_payload...` |
| Email: store has database-level tests | **PASS** | §12, 13 tests |
| Email: no PII in durable state | **PASS** | §8 |
| Document: stale write refused | **PASS** | §11, 100 iterations |
| Document: source never rewritten | **PASS** | §10, §11 |
| Document: failure cannot demote success | **PASS** | §10 |
| Document: re-crawl invalidates pass | **PASS** | §11 |
| Document: tenant-isolated | **PASS** | §11, §13 |
| Document: fake/Mongo parity | **PASS** | §13, real mongod |
| Shadow: no durable email state | **PASS** | `..._no_duplicate_side_effects.py` |
| Phase 17B invariants | **PASS** | §16 |
| Determinism ×3 | **PASS** | §15 |
| Unknown delivery past provider window | **PARTIAL** | §20 — escalated, not resolved |
| Delivery-store retention | **NOT MEASURED** | §23 |
| Queue cutover | **NOT MEASURED** | §17 — not attempted |

---

## 25. Commands to reproduce

```bash
# full suite
.venv/bin/python -m pytest tests/ backend/

# queue, prototypes, shadow harness
.venv/bin/python -m pytest backend/queue/tests/ backend/prototypes/ \
  tests/test_queue_shadow_validation_harness.py

# the delivery store against a real database (needs the prototype mongod)
.venv/bin/python -m pytest tests/test_email_delivery_repository.py

# concurrency-sensitive selection, three times
for i in 1 2 3; do .venv/bin/python -m pytest \
  backend/queue/tests/test_document_redelivery.py \
  tests/test_document_repository.py \
  tests/test_email_delivery_repository.py \
  backend/queue/tests/test_email_idempotency_integration.py \
  backend/queue/tests/test_ownership_races.py \
  backend/queue/tests/test_shadow_no_duplicate_side_effects.py \
  -p no:randomly; done

# gates
.venv/bin/ruff check backend tests scripts
.venv/bin/mypy backend
bash scripts/check-backend.sh
bash scripts/check-input-validation.sh      # exit 1, 21/22: 1 known pre-existing failure

# shadow harness
.venv/bin/python scripts/queue_shadow_validation.py
```

Do not add a second `-q`: `pyproject.toml` already sets `addopts = "-q"`, and `-qq`
makes pytest omit the final count line, so a passing run looks like it produced no
results (§14).

---

## 26. What a PASS does and does not authorize

This report authorizes **no deployment**. It establishes that the two Phase 17B
correctness blockers are closed and that the suite would catch their return.

It does **not** establish exactly-once email delivery, and the report does not claim it.
The strongest honest statement is: *for every delivery whose outcome the system knows, a
duplicate is impossible; for one delivery class whose outcome the provider never reported,
the system escalates rather than duplicating or silently dropping.*

Cutover remains gated on the separate questions Phase 17B left open (§16, §23 of that
report), none of which this phase addressed.
