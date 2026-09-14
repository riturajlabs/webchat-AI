# FIND-05 Investigation — `CRAWL_NO_SANDBOX=true` Contradicts the Non-Root Production Posture

- Status: **INVESTIGATION ONLY** (no code/config/test changes made or committed)
- Current HEAD: `9b64519` (`main`, ahead 7)
- Date: 2026-09-12
- Verdict: **STILL VALID** at HEAD `9b64519`

---

## Canonical finding

From `docs/WORKER_COMPREHENSIVE_PRODUCTION_AUDIT_2026-09-12.md:123-128`:

> **FIND-05 (P2) — `CRAWL_NO_SANDBOX=true` in the production template contradicts the code policy.**
>
> - File:line: `.env.production.example:370` sets `CRAWL_NO_SANDBOX=true`; `config.py:347-351` documents sandbox-on as the production posture and says no-sandbox is "never the default".
> - Problem: the shipped production config runs Chromium with the sandbox disabled inside a non-root container.
> - Impact: defence-in-depth loss if a crawled hostile page exploits a Chromium rendering bug (browser runs untrusted web content by design). This is exactly the crawler's threat model.
> - Fix: re-derive at deploy time whether the Railway container truly cannot sandbox (user namespaces); if it can, ship `CRAWL_NO_SANDBOX=false`. At minimum, add an explicit comment + runtime warning when no-sandbox is enabled.
> - Risk: if the runtime genuinely refuses sandboxing, disabling it may be the only option — hence "validate, don't blindly revert". Effort: S.

Related port of the Sep 4 register: `docs/FINAL_ISSUE_REGISTER.md:31` (SEC-L05) flagged the _default_ (`core/config.py:327` at that time, `crawl_no_sandbox defaults to True`). That default was subsequently flipped to `False` (`e504879`, 2026-09-09), so the register-level default issue is closed; the FIND-05 template/value contradiction was NOT addressed.

Severity: **P2** (SECURITY / defence-in-depth).

---

## Code path traced (entry → affected behavior)

1. **Config**: `backend/core/config.py:351` — `crawl_no_sandbox: bool = False` (sandbox-on default), with the policy documented at `config.py:347-350` ("The production posture is to run with Chromium sandboxing enabled ... Set CRAWL_NO_SANDBOX=true only when the runtime genuinely cannot sandbox ... never the default"). Parsed from env var `CRAWL_NO_SANDBOX` (pydantic-settings, `case_sensitive=False`).
2. **Production template**: `.env.production.example:369-370`:
   - comment: `# Set false behind a non-root production image (Chrome sandbox).`
   - value: `CRAWL_NO_SANDBOX=true` — the comment and the value directly contradict each other.
3. **Compose**: `docker/compose.yml:228` — default `${CRAWL_NO_SANDBOX-true}` feeds the worker. `docker/compose.prod.yml` does **not** override it, so the production overlay inherits the base default (`true`). The base file itself documents the unsafe assumption at `docker/compose.yml:453-454`: "Chromium with --no-sandbox (CRAWL_NO_SANDBOX=true) runs without special capabilities. cap_drop ALL is safe here."
4. **Container**: `docker/Dockerfile.worker` — non-root `USER appuser` (`:71`), `cap_drop ALL` + `no-new-privileges` in compose (`docker/compose.yml:451-456`), so the SUID-setuid sandbox helper is impossible; Chromium's user-namespace sandbox is the only isolation mechanism the runtime could use (`Dockerfile.worker:55-57` explicitly describes this).
5. **Browser launch**: `backend/services/ingestion/browser.py:68-74` — when `settings.crawl_no_sandbox` is true, `--no-sandbox` is appended; the launch is logged at **INFO** level only (`crawl_browser_launch no_sandbox=...`). **No WARNING/error level is raised when the sandbox is disabled.**
6. **Trigger surface**: the crawler is HTTP-first (`CRAWL_HTTP_FIRST=true`, `.env.production.example:374`), so Chromium only loads pages judged to need JS. That is precisely the attacker-controlled, untrusted-rendering surface the audit describes.

## Is it still valid, fixed, or materially changed?

**STILL VALID — unchanged at HEAD `9b64519`.**

Check against the four post-audit fix commits:

- `3d78866` (FIND-02 single-flight fencing) — unrelated to sandbox.
- `3b60478` (FIND-03 worker logging) — touched `browser.py` only to redact URLs (`safe_url_parts`); did **not** add a no-sandbox warning and did not change the INFO log.
- `b0c4ff4` (FIND-07 robots fail-closed) — touched `.env.production.example` (added `CRAWL_ROBOTS_FAIL_OPEN=false`) — sandbox line untouched.
- `9b64519` (FIND-06 worker sizing) — added `_log_resource_caps()` startup logging; sandbox untouched.

No commit at or before HEAD changes `.env.production.example:370`, `config.py:351`, or `browser.py:68-74`. `git log -S` shows the `CRAWL_NO_SANDBOX=true` value and the contradictory comment were both introduced in `1cbac7c` (2026-08-28) and never re-derived.

## Root cause

The safe code default was fixed (`crawl_no_sandbox: bool = False`), but the **shipped production configuration** still explicitly forces the unsafe value (`true`) both in `.env.production.example:370` and as the compose interpolation default (`docker/compose.yml:228`), overriding the code default and policy. The contradictory comment at `.env.production.example:369` ("Set false behind a non-root production image") codifies the intent that was not honored. No deploy-time user-namespace validation exists anywhere in the repo, and the audit's minimum mitigation (a runtime warning when no-sandbox is enabled) is absent.

## Production impact

- **Security (defence-in-depth):** a page that exploits a Chromium renderer/fuzzer bug escapes the renderer with the appuser context _without_ Chromium's namespace/seccomp isolation. The container still has `cap_drop ALL`, `no-new-privileges`, non-root user and (prod overlay) read-only FS, so this is layered-containment loss, not an unconditional host RCE.
- **Exposure is real but scoped:** only JS-fallback pages reach Chromium; but those pages are the most attacker-controlled content the crawler processes.
- **No correctness/performance/data-loss impact** — the finding is purely about isolation strength, not job correctness.

## Existing mitigation

- Non-root `appuser`, `cap_drop ALL`, `no-new-privileges` (compose base), read-only root FS + tmpfs (prod overlay).
- `config.py:347-351` policy comment.
- The contradictory comment at `.env.production.example:369` (intent documented, not enforced).
- No runtime warning. No tests asserting sandbox args (`test_browser_lock.py` covers concurrency only).

## Recommended remediation (smallest production-safe, matches audit "validate, don't blindly revert")

1. **Deploy-time re-derivation (gating step, infrastructure):** in the real Railway worker container, verify user-namespace availability (e.g. run `/proc/sys/kernel/unprivileged_userns_clone` / a Playwright smoke launch with sandbox on). If user namespaces work (expected for a modern non-root container), change the shipped value to `CRAWL_NO_SANDBOX=false` in `.env.production.example` and the compose path.
2. **Runtime warning (code, minimal):** in `browser.py`, log at `WARNING` level (or emit a structured `worker_no_sandbox_toast`-style event) whenever `settings.crawl_no_sandbox` is true, so any future regressions to no-sandbox are visible in boot/launch logs.
3. **Comment/codify:** fix the contradictory comment at `.env.production.example:369`; align `docs/CRAWL_EGRESS_HARDENING.md:105` (§6 preserved-values list) and the `docker/compose.yml:453-454` note with whichever value is re-derived.
4. **Escape hatch preserved:** do not hard-fail if the runtime genuinely cannot sandbox — keep `CRAWL_NO_SANDBOX=true` as the deployable fallback, but document it.

## Alternatives considered

- **Blindly flip to `false` everywhere** — rejected. If Railway's runtime blocks unprivileged user namespaces, Chromium refuses to launch and every JS-page crawl breaks (the audit's explicit "validate, don't blindly revert" warning). Must be gated on a real deployment test.
- **Hard-fail boot check** (`raise` when no-sandbox in production) — rejected for the same reason; would make an environment that legitimately needs no-sandbox unable to crawl at all.
- **Remove `--no-sandbox` support entirely** — rejected; loses the legitimate escape hatch and contradicts the audit's intent.
- **Config validator rejecting no-sandbox in production** (`model_validator`) — could be layered in later only after Railway capability is proven; not the minimal first step.

## Tests / validation performed (read-only)

- Read canonical audit FIND-05 block, §9 Browser (VERIFIED), §22 fix order, §23 quick wins, §25 do-not-change.
- Confirmed FIND-05 unchanged across `3d78866`/`3b60478`/`b0c4ff4`/`9b64519` (`git show --stat`, `git log -S`).
- Confirmed `.env.production.example:369-370` value+comment present and contradictory at HEAD; b0c4ff4 only added `CRAWL_ROBOTS_FAIL_OPEN`.
- Confirmed `docker/compose.prod.yml` does not override `CRAWL_NO_SANDBOX` (inherits base `${CRAWL_NO_SANDBOX-true}`).
- Confirmed `browser.py` logs no-sandbox at INFO only; `backend/workers/app.py` startup has resource-cap logging but no sandbox check.
- Confirmed `Dockerfile.worker` runs non-root `appuser`.
- Read-only settings parse: default `False`; env override `True` honoured.
- Confirmed git working tree unchanged and nothing staged.

## Files that would need modification IF implementation is approved

- `.env.production.example` (value + comment, gated on Railway validation)
- `docker/compose.yml` (:228 default, :453-454 comment)
- `backend/services/ingestion/browser.py` (WARNING on no-sandbox)
- `docs/CRAWL_EGRESS_HARDENING.md` (§6 preserved values) — audit docs unchanged
- Optionally `backend/workers/app.py` (startup warning) — could live in `browser.py` instead
- New test file (e.g. `tests/test_browser_sandbox.py`) asserting launch args / warning

## Residual risks

- Railway user-namespace capability is unproven at the time of writing; remediation is deliberately gated on a deployment smoke test.
- HTTP-first means the browser path only runs for JS-required pages — lower frequency but the attacker-controlled surface remains.
- No CI assertion pins the sandbox value; a future commit could reintroduce no-sandbox silently even after the runtime warning lands.
