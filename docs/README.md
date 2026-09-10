# WebChat AI — Documentation

Index of platform documentation. This repository treats **canonical (living)**
documents separately from **historical (dated) audit & verification reports.

> **Ground-truth ordering:** when a document disagrees with the current
> implementation, the source code wins, then the automated tests, then
> package/config files, then deployment configuration, then this documentation.
> History files below are preserved as a record, not as current guidance.

## Canonical / living docs

| Document                                                     | Purpose                                                            |
| ------------------------------------------------------------ | ------------------------------------------------------------------ |
| [01-PRD.md](01-PRD.md)                                       | Product requirements                                               |
| [02-TRD.md](02-TRD.md)                                       | Technical requirements                                             |
| [03-App-Flow.md](03-App-Flow.md)                             | Application flows                                                  |
| [04-UI-UX-Brief.md](04-UI-UX-Brief.md)                       | UI/UX design brief                                                 |
| [05-Backend-Schema.md](05-Backend-Schema.md)                 | Database schema                                                    |
| [06-Implementation-Plan.md](06-Implementation-Plan.md)       | Phased implementation plan                                         |
| [07-Architecture-Decisions.md](07-Architecture-Decisions.md) | Architecture decision record (ADR) — ADR-001…ADR-009               |
| [deployment/README.md](deployment/README.md)                 | Production deployment: images, rollout, rollback, probes, alerting |

## Folder READMEs (orientation)

In addition to this index, each subsystem has its own README, which is the
first place to look for that area:

| Area       | README                                                       |
| ---------- | ------------------------------------------------------------ |
| Platform   | [../README.md](../README.md)                                 |
| Backend    | [../backend/README.md](../backend/README.md)                 |
| Dashboard  | [../apps/dashboard/README.md](../apps/dashboard/README.md)   |
| Widget SDK | [../apps/widget/README.md](../apps/widget/README.md)         |
| Themes     | [../packages/themes/README.md](../packages/themes/README.md) |
| Docker     | [../docker/README.md](../docker/README.md)                   |
| Tests      | [../tests/README.md](../tests/README.md)                     |
| Scripts    | [../scripts/README.md](../scripts/README.md)                 |

## Historical audit & verification reports

Dated/finalized reports are retained for the record. They reflect the state of
the code at the time of writing; treat them as history, and re-verify any claim
against the current implementation before acting on it.

### Production readiness

- `FINAL_PRODUCTION_READINESS_AUDIT.md`
- `FINAL_ISSUE_REGISTER.md`
- `OPTIMIZATION_ROADMAP.md`
- `FINAL_RAG_REMAINING_ISSUES_2026-09-04.md`

### RAG accuracy & latency investigations

- `RAG_ACCURACY_LATENCY_AUDIT.md`
- `RAG_MANUAL_REGRESSION_CRAWL_COVERAGE_2026-09-09.md`
- `RAG_ACCURACY_TTFT_BENCHMARK_2026-09-07.md`
- `RAG_ACCURACY_TTFT_DEEP_DIVE_2026-09-07.md`
- `RAG_BASELINE_INSTRUMENTATION_2026-09-07.md`
- `RAG_REAL_TTFT_BENCHMARK_2026-09-08.md`
- `RAG_REAL_PRODUCTION_TTFT_2026-09-08.md`

### RAG optimizations (dated)

- `RAG_OPTIMIZATION_ACC03_2026-09-08.md`
- `RAG_TTFT_EMBEDDING_OPTIMIZATION_2026-09-08.md`
- `RAG_TTFT_PREGENERATION_OPTIMIZATION_2026-09-08.md`
- `RAG_TTFT_PROVIDER_GENERATION_OPTIMIZATION_2026-09-09.md`
- `RAG_TTFT_REDIS_HEALTH_OPTIMIZATION_2026-09-08.md`
- `RAG_TTFT_RERANKER_ANALYSIS_2026-09-08.md`
- `RAG_TTFT_STREAMING_WATERFALL_2026-09-08.md`

## AI-development rules

- [`../00-AI-Development-Rules.md`](../00-AI-Development-Rules.md) — mandatory
  rules for AI coding agents working in this repository.
