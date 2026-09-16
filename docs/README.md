# WebChat AI — Documentation

Index of platform documentation. Canonical (living) documents are the source
of truth for how the product works.

> **Ground-truth ordering:** when a document disagrees with the current
> implementation, the source code wins, then the automated tests, then
> package/config files, then deployment configuration, then this documentation.

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

## Reference docs

- `CRAWL_EGRESS_HARDENING.md` — crawler egress/access strategy design
- `DATABASE_BACKUP_RESTORE.md` — MongoDB backup & restore procedures
- `OPTIMIZATION_ROADMAP.md` — forward-looking performance roadmap

## Working drafts

- `README_DOCUMENTATION_FORENSIC_AUDIT_2026-09-16.md` — documentation-ecosystem
  audit (temporary working draft; superseded by the READMEs above)

## AI-development rules

- [`../00-AI-Development-Rules.md`](../00-AI-Development-Rules.md) — mandatory
  rules for AI coding agents working in this repository.
