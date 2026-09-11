# Crawl Egress Hardening — target-blocking classification & observability

Status: implemented (backend + dashboard + docs).

## 1. Background / root-cause model

Indira University (`indirauniversity.edu.in`) returned **HTTP 403 to the Railway
Worker** for both the HTTP-first path AND the Playwright/headless-Chromium
fallback, so the crawl stored zero pages and ended `failed`. Portfolio-style
websites crawled from the **same Worker and same IP** successfully.

Model of the failure:

| Layer                                                | Status                                                                            |
| ---------------------------------------------------- | --------------------------------------------------------------------------------- |
| Crawler logic (HTTP-first → browser→ classification) | Application-level; fixed by this change                                           |
| Target edge/WAF policy (403 for our egress)          | Target-site/network-level; not fixable in code                                    |
| Railway egress IP allow-listing                      | Infrastructure-level; requires Static Outbound IPs or customer-side allow-listing |

The crawler cannot "fix" a website that rejects its egress. What it must do —
and now does — is **fail honestly**: classify the rejection, stop retrying,
preserve any existing knowledge base, and surface a safe message. Do not treat
this change as a guarantee that Indira University will crawl successfully; that
only follows a real Railway deployment whose egress the site accepts.

## 2. Failure classification vocabulary

Stored on `CrawlJob.errors[]` and exposed on the dashboard:

`success`, `retryable_network_error`, `target_rate_limited`, `target_blocked`,
`target_server_error`, `target_not_found`, `unsupported_content`,
`ssrf_blocked`, `invalid_url`, `browser_launch_failure`, `crawl_timeout`,
`unknown_failure`.

A structured error also carries `status_code`, `method` (`http`|`browser`) and
`attempt` — no parsing of message strings, no internal detail exposed to users.

## 3. Retry policy (bounded)

| Condition               | Behaviour                                                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| HTTP 403                | Fall back to the browser once. If the browser also gets 403 → `target_blocked`. No HTTP retry (never a storm).                                                     |
| HTTP 429                | Respect `Retry-After`, capped at `CRAWL_RETRY_MAX_WAIT_SECONDS` (default 30 s); bounded HTTP retries then browser fallback → `target_rate_limited` when exhausted. |
| HTTP 5xx                | Bounded exponential backoff (`CRAWL_RETRY_BACKOFF_BASE_SECONDS`/`_CAP_SECONDS`), then browser fallback where the existing policy applies → `target_server_error`.  |
| Timeout / network error | Bounded immediate retry (`CRAWL_HTTP_MAX_ATTEMPTS`, default 2), then browser fallback.                                                                             |
| 404 / 410               | No browser retry → `target_not_found`.                                                                                                                             |
| SSRF / invalid URL      | Fail immediately, no fallback, no leak.                                                                                                                            |
| Browser launch failure  | `browser_launch_failure` — never mistaken for a hostile website.                                                                                                   |
| Site persists 403/429   | Per-host budget `CRAWL_MAX_BLOCKED_PAGES_PER_HOST` (default 10): stop early and finish deterministically.                                                          |

Global caps are unchanged: `CRAWL_MAX_PAGES`, `CRAWL_MAX_DEPTH`,
`CRAWL_NAVIGATION_TIMEOUT_MS`, `CRAWL_MAX_HTML_BYTES`, `CRAWL_MAX_CONTENT_BYTES`
— the new retry knobs are additional ceilings, never larger budgets.

## 4. Observability

Structured log events:

`crawl_fetch_attempt`, `crawl_http_error`, `crawl_http_retry`,
`crawl_browser_fallback_start`, `crawl_browser_launch_success`,
`crawl_browser_launch_failed`, `crawl_browser_http_error`, `crawl_browser_success`,
`crawl_target_blocked`, `crawl_target_rate_limited`, `crawl_page_stored`,
`crawl_finished`.

For blocked/rate-limited targets the log carries `tenant_id`, `website_id`,
`crawl_job_id`, `hostname`, normalized `path` (query/fragment stripped),
`status_code`, `method`, `attempt`, `elapsed_seconds`, `existing_pages`.

A crawl that still stores pages but is stopped early by the per-host blocked
cap logs `crawl_finished … status=completed reason=blocked_host_aborted` (the
stored pages are kept; only the remaining budget is surrendered).

Prometheus (`CRAWL_FETCH_FAILURES_TOTAL`):

```
crawl_fetch_failures_total{classification,status_code,method}
```

Labels are fixed and low-cardinality — **never** full URLs, tenant ids or job ids.
Secrets are further protected by the existing `SensitiveDataFilter` (tokens,
`Authorization` headers, bearer JWTs, passwords auto-redacted) and by logging
hostname + path only for terminal events.

## 5. User-facing behaviour

- New website, zero pages, target rejected (403): job `failed`, message
  “The website rejected automated crawling (HTTP 403).”, dashboard shows
  “Crawl blocked”.
- New website rate-limited: job `failed`, “The website is rate-limiting
  automated requests.”, dashboard shows “Crawl rate-limited”.
- Existing website whose refresh is blocked: **existing documents are never
  deleted**; website stays `ready` with its previous `pages_indexed`, the job is
  `failed`, and the message appends “Your existing knowledge base is still
  available.”

Railway IP addresses, internal hostnames, stack traces and secrets are never
shown to dashboard users.

## 6. 1 GiB Railway Worker constraints (do not raise)

These values are preserved by the production configuration:

```
CRAWL_HTTP_FIRST=true
CRAWL_NO_SANDBOX=true
CRAWL_MAX_CONCURRENT=1
EMBEDDING_MAX_CONCURRENT_BATCHES=1
```

Do **not** increase browser concurrency, embedding concurrency, or crawl
concurrency. One shared headless Chromium is launched lazily; context/page/close
cleanup is `finally`-based on success, HTTP error, timeout, exception, and
cancellation.

## 7. Railway Static Outbound IPs (infrastructure, not code)

Static Outbound IP is **primarily an infrastructure configuration** — this
repository does not, and must not, fake static-IP behaviour in application code.

For Railway (Pro plan) `webchat-ai-worker`:

1. Open the `webchat-ai-worker` service.
2. Go to **Settings → Networking**.
3. Enable **Static Outbound IPs**.
4. Record all assigned IPv4 addresses.
5. Redeploy the Worker.
6. If the target website/firewall is controlled by the customer, allow-list
   those IPs (region-specific).

Railway assigns multiple static outbound IPs for high-throughput/resilience and
balances outbound traffic across them. These addresses are **region-specific and
not guaranteed to be dedicated**.

**Important caveats**

- Static Outbound IP is an infrastructure capability; it does not guarantee that
  every WAF will allow the crawler.
- The application must still handle `target_blocked` gracefully (it does).
- Indira University is only considered fixed after a real Railway crawl succeeds.

## 8. Tests

Focused hardening coverage lives in `tests/test_crawl_egress_hardening.py`
(deterministic mocks, no live websites):

HTTP 403 → browser fallback; 403+browser 403 → `target_blocked`; 403+browser
success → page stored; 429 bounded retry; `Retry-After` bounded; 404 no
fallback; SSRF no fallback; browser-launch classification; browser-timeout
classification; zero-page blocked new website → `failed`; blocked refresh
preserves old documents; secrets absent from structured logs; no
high-cardinality metric labels; cleanup after browser failure and cancellation;
`CRAWL_MAX_CONCURRENT=1` respected; existing Portfolio-style crawl unchanged.
