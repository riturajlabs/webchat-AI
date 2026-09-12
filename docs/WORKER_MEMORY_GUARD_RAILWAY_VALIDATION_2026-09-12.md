# Railway Worker Memory-Guard Runtime Validation (FIND-01)

- **Date of measurements:** 2026-09-12, ~09:58–09:59 UTC
- **FIND-01 commit under test:** `9123adb` (`fix: make worker memory guard container-aware`)
- **Mode:** measurement-only; read-only on the repo and on production. No source/test/config change, no commit, no push, no restart/redeploy of any production worker, no `CRAWL_MAX_RSS_MB` change (remains `0`), no hard ceiling enabled.

## 1. Railway runtime shape (as assessed)

Relevant resource envelope and entrypoint to reproduce:

- 2 vCPU / 1 GiB RAM, single worker replica
- `docker/Dockerfile.worker`, start command `python -m backend.workers`
- HTTP-first crawler (`CRAWL_HTTP_FIRST=true`), `CRAWL_MAX_CONCURRENT=1`,
  `EMBEDDING_MAX_CONCURRENT_BATCHES=1`, `CRAWL_MAX_RSS_MB=0`

**Method.** Railway's live platform was not reachable from this environment
(no `railway` CLI/credentials; attaching to or redeploying the production
worker from here is disallowed by the validation constraints). Instead the
worker image was rebuilt untouched from the current tree
(`docker build -f docker/Dockerfile.worker`) and run in a throwaway container
under the **exact Railway resource envelope**: `--cpus=2 --memory=1024m
--memory-swap=1024m` (swap strictly disabled so the cgroup limit is the
container limit). Inside the container, `/sys/fs/cgroup` is the container's
own delegated cgroup namespace — the same topology Railway presents to its
worker — so `memory.current`/`memory.max` are container-scoped, which is the
read the FIND-01 guard uses on Railway. The running dev stack containers
(`webchat-worker`, etc.) were **not** touched.

## 2. Cgroup topology (read-only, from inside the container)

| item                                          | value                                                                                                                          |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `/proc/self/cgroup`                           | `0::/`                                                                                                                         |
| `/sys/fs/cgroup/memory.current`               | `61063168` at boot → 57–58 MiB idle                                                                                            |
| `/sys/fs/cgroup/memory.max`                   | `1073741824` (**1024 MiB = 1 GiB**)                                                                                            |
| `/sys/fs/cgroup/memory/memory.usage_in_bytes` | absent (v2 only)                                                                                                               |
| `/sys/fs/cgroup/memory/memory.limit_in_bytes` | absent (v2 only)                                                                                                               |
| cgroup version                                | **v2** (unified)                                                                                                               |
| membership vs mount root                      | identical (`0::/` — the container root). No deeper delegated path to distinguish here, unlike the dev host (`0::/init.scope`). |

The process membership path and the mount root coincide in this container
topology; the cgroup files are exactly container-scoped, so
`measure_memory()` reads the 1 GiB-limited container itself.

## 3. Worker idle baseline (3 observations, ~12 s apart)

| sample | source    | cgroup current MiB | python RSS MiB | container procs | chromium procs |
| ------ | --------- | -----------------: | -------------: | --------------: | -------------: |
| idle_0 | cgroup_v2 |               58.2 |             68 |               1 |              0 |
| idle_1 | cgroup_v2 |               57.7 |             68 |               1 |              0 |
| idle_2 | cgroup_v2 |               57.5 |             68 |               1 |              0 |

**min 57.5 / median 57.7 / max 58.2 MiB** (cgroup current, container-scoped).
`measure_memory().limit_mib = 1024.0` on every sample. No shared browser
resident at idle (0 chromium procs).

## 4. HTTP-first crawl (example.com — IETF-controlled, minimal load)

| sample | cgroup MiB | python RSS MiB | procs | chromium |
| ------ | ---------: | -------------: | ----: | -------: |
| pre    |       56.6 |             68 |     1 |        0 |
| post   |   **59.2** |             71 |     1 |        0 |

- `html_bytes = 559`, fetched via `HybridPageFetcher.fetch()` (the production
  fetcher). Verdict was HTTP-sufficient (no browser fallback).
- **Chromium was NOT launched**: 0 chromium processes before and after.
- HTTP-first peak **~59 MiB** (+~3 MiB over idle, httpx client + response).

## 5. Targeted JS/browser fallback (playwright.dev — single page)

Drives the production `BrowserPageFetcher` (same class the worker uses after a
`JS_REQUIRED` verdict or a non-recoverable HTTP rejection).

| sample                                   | cgroup MiB | python RSS MiB | proc-sum RSS MiB | procs | chromium |
| ---------------------------------------- | ---------: | -------------: | ---------------: | ----: | -------: |
| pre-browser-launch                       |       59.2 |             71 |               71 |     1 |        0 |
| during fetch (browser launched)          |  **405.0** |             62 |              462 |     8 |        6 |
| after `fetcher.close()` (context closed) |      368.4 |             62 |              457 |     7 |    **5** |

- `html_bytes = 21832`; peak cgroup current **405 MiB**.
- Chromium is the dominant consumer: ~+346 MiB over the HTTP-first footprint;
  python RSS stays ~60–70 MiB throughout.
- **`BrowserPageFetcher.close()` closes only the per-job browser context; the
  shared Chromium instance remains resident** (5–6 chromium processes).
  Confirmed explicitly — matches the FIND-01 design finding.

## 6. Post-browser idle (3 observations, ~12 s apart)

| sample | cgroup MiB | python RSS MiB | procs | chromium |
| ------ | ---------: | -------------: | ----: | -------: |
| t0     |      368.2 |             62 |     7 |        5 |
| t1     |      279.3 |             58 |     7 |        5 |
| t2     |  **241.8** |             56 |     7 |        5 |

**min 241.8 / median 279.3 / max 368.2 MiB.** The shared browser remains
resident; its footprint settles as Chromium releases page/renderer caches.
Standing post-JS footprint ≈ **242–368 MiB**, ~4× the python-only baseline.

## 7. Second crawl (HTTP-first, browser still resident)

| sample | cgroup MiB | python RSS MiB | procs | chromium |
| ------ | ---------: | -------------: | ----: | -------: |
| pre    |      245.1 |             56 |     7 |        5 |
| post   |      245.9 |             61 |     7 |        5 |

HTTP-first job after the browser crawl adds only **~+1 MiB** on top of the
standing footprint. The resident Chromium (5 procs) persists **into later
jobs** — a single JS job permanently raises the worker's standing memory.

## 8. Peak / median summary (cgroup current MiB, container-scoped)

| phase                   |      peak | median / settled |
| ----------------------- | --------: | ---------------: |
| idle baseline           |      58.2 |             57.7 |
| HTTP-first crawl        |      59.2 |              ~58 |
| JS/browser crawl        | **405.0** |                — |
| post-browser standing   |     368.2 |            241.8 |
| second HTTP-first crawl |     245.9 |             ~245 |
| final standing          |     246.0 |            246.0 |

## 9. Python vs container vs python-tree comparison

- python RSS (single procs, `/proc/self/status VmRSS`): **56–71 MiB** throughout.
- cgroup `memory.current` (container-scoped): **57.5–405 MiB** depending on
  browser activity.
- proc-total RSS (`/proc/*/statm` summed over container pids): **68–462 MiB**,
  tracking cgroup closely (page-cache accounting explains small deltas).

Chromium is decisively the dominant consumer (~340–400 MiB); the Python
worker is ~60–70 MiB. The pre-FIND-01 `ru_maxrss`-based guard (python-only)
could see at most ~176 MiB and was blind to this.

## 10. Chromium process behaviour

- HTTP-first path: **0 chromium processes** (verified before and after fetch).
- After first JS use: 6 chromium processes during fetch, **5 remaining after
  the context closes**, staying resident through post-idle and into the second
  crawl.
- Chromium is torn down only by `close_browser()` (worker shutdown), not by
  per-job context close — so the standing footprint of any worker that has
  ever used JS is ~242–368 MiB, not ~58 MiB.

## 11. Actual `memory.max`

`1073741824` bytes = **1024 MiB (1 GiB)**, enforced via the container limit
(swap disabled). The FIND-01 reader sees exactly this limit (`limit_mib =
1024.0`), so the guard's cgroup source is fully container-scoped on this
runtime shape.

## 12. Headroom (relative to the measured 1024 MiB limit)

- Worst observed local peak (JS crawl): **405 MiB → 619 MiB headroom
  (60.4% free)**.
- Standing with resident Chromium: **~246 MiB → ~778 MiB headroom (76%)**.
- Idle python-only: **~58 MiB → ~966 MiB free**.
- HTTP-only crawl: **~59 MiB peak**.

Unmeasured worst cases that consume the headroom: a 5 MB-cap page with a deep
DOM (page memory scales with DOM size), the embedding phase, and
Chromium's own fragmentation under sustained multi-page use.

## 13. Guard visibility (no ceiling enabled)

`CRAWL_MAX_RSS_MB=0` (default, unchanged) — the guard's trigger path is
disabled by design and produced no logs. Measurements were collected with the
same `measure_memory()` code path the guard uses (source `cgroup_v2`, current
container-scoped, `limit_mib=1024`), i.e. the production measurement is valid
on this runtime shape. No temporary production logging was added.

## 14. Limitations

- Run on a container built from the **same `Dockerfile.worker` image at the
  Railway resource envelope**, not on Railway's physical platform (no CLI/
  credentials; production untouched). The cgroup topology presented to the
  worker is equivalent to Railway's.
- One crawl per mode, single modest pages (example.com 559 B; playwright.dev
  21 KB). No max-size (5 MB) / deep-DOM page, no embedding phase, no soak.
- `0::/` membership == mount root here, so the "membership deeper than root"
  case (which the P2 fix guards against) does not occur in this topology.

## 15. Final classification

**B — NEEDS MORE SOAK.** Findings are promising and clearly container-scoped
(peak 405 MiB / 1024 MiB = 40%, standing ~246 MiB), so a 1 GiB Railway worker
has strong _measured_ headroom. But a single JS crawl on one short page cannot
yet bound the worst-case render the worker can produce (5 MB HTML cap, deep
DOM, embedding phase, sustained Chrome fragmentation), and this ran off the
actual platform. That is insufficient to establish a reliable production
ceiling.

**Hard ceiling: NOT enabled.** `CRAWL_MAX_RSS_MB` remains `0`.

Path to A (soak plan): repeat the browser crawl against (a) a max-size/JS-heavy
page, (b) a multi-page site (frontier + robots + embeddings), and (c) an
extended idle — then set a ceiling with ≥20% headroom over the observed worst
peak if the worst stays well under ~1 GiB.

## 16. Safety

Verified the container limit was never approached (peak 405 MiB vs 1024 MiB),
no OOM, no degradation. The running production worker was not restarted,
redeployed, or logged into; MongoDB/Redis/subscription/user/crawler data from
the existing docker-compose stack were not altered (no ARQ jobs enqueued, no
repository writes).
