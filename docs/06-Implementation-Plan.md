# WebChat AI - Implementation Plan

**Version:** 2.0  
**Project Name:** WebChat AI  
**Document Type:** Implementation Plan  
**Development Methodology:** Agile + AI-Assisted Development (Cursor / Claude Code)  
**Author:** Ritu Raj  
**Status:** Draft  
**Last Updated:** August 2026

---

# 1. Overview

This document defines the complete implementation roadmap for building **WebChat AI**, a production-ready, multi-tenant, cloud-native RAG SaaS platform.

Development is divided into multiple phases to ensure each feature is fully implemented, tested, and documented before moving to the next phase.

---

# 2. Development Principles

The AI coding agent must follow these principles:

- Build production-ready code only.
- Complete one phase before starting the next.
- No placeholder implementations.
- Security-first development.
- Test every feature before marking it complete.
- Follow SOLID, DRY, and KISS principles.
- Use reusable and modular architecture.
- Every feature must be documented.

---

# 3. Project Folder Structure

```text
webchat-ai/

apps/
├── dashboard/
├── widget/

backend/
├── api/
├── core/
├── models/
├── services/
├── repositories/
├── workers/
├── ai/
├── utils/

docs/

docker/

scripts/

tests/
```

---

# Phase 1 — Project Foundation

## Goal

Prepare the development environment and project architecture.

### Tasks

- Initialize Git repository
- Create monorepo structure
- Setup Next.js
- Setup FastAPI
- Configure TypeScript
- Configure Python virtual environment
- Configure Docker
- Setup MongoDB Atlas
- Setup Redis
- Configure environment variables
- Configure ESLint
- Configure Prettier
- Configure Husky
- Configure GitHub Actions

### Deliverables

- Running frontend
- Running backend
- MongoDB connected
- Redis connected
- CI pipeline working

### Definition of Done

- Project builds successfully.
- No configuration errors.
- Docker containers start correctly.

---

# Phase 2 — Authentication System

## Goal

Implement secure authentication.

### Tasks

- Signup
- Login
- Logout
- JWT Authentication
- Refresh Tokens
- Argon2 Password Hashing
- Email Verification
- Forgot Password
- Reset Password
- RBAC

### Security

- Rate limiting
- Secure Cookies
- CSRF Protection
- Input Validation

### Deliverables

- Complete authentication system

### Definition of Done

- Authentication passes all tests.

---

# Phase 3 — Website Management

## Goal

Allow users to connect websites.

### Tasks

- Add Website
- Validate URL
- Delete Website
- Edit Website
- Website Status
- Widget Generation

### Validation

- Duplicate detection
- Invalid URLs
- HTTPS enforcement

### Deliverables

- Website management dashboard

---

# Phase 4 — Data Ingestion Engine

## Goal

Automatically build the knowledge base.

### Tasks

- Playwright crawler
- Dynamic page rendering
- HTML cleaning
- Readability extraction
- Metadata extraction
- Internal link crawling
- Crawl queue
- Retry logic

### Security

Prevent

- SSRF
- Infinite crawl
- Private IP crawling

### Deliverables

- Reliable crawler

### Status — COMPLETE (August 2026)

The Phase 4 ingestion engine is implemented, tested, and verified end-to-end:

- Playwright/Chromium crawler with dynamic rendering (`backend/services/ingestion/crawler.py`, `browser.py`).
- Readability-style extraction and HTML cleaning (`extractor.py`, `cleaner.py`); per-page metadata (title, language, checksum).
- Internal-link BFS crawl with configurable depth (default 3) and per-job page cap (default 50).
- ARQ crawl job (`backend/workers/jobs/crawl.py`) with retry/backoff, permanent failure on invalid seeds, and a process-wide concurrency semaphore.
- SSRF protection with per-request DNS re-validation and private/internal range blocking (`ssrf_guard.py`); robots.txt compliance (`utils/robots.py`); URL normalization (`utils/url_validator.py`).
- Incremental, idempotent writes: `documents` upserted on the unique `(tenant_id, website_id, url)` key with a SHA-256 content checksum (Phase 5 input).
- `crawl_jobs` + `documents` models, tenant-scoped repositories, `POST /api/websites/{id}/crawl` and `GET /api/crawl-jobs/{id}` endpoints.
- Dashboard crawl controls (start, status, progress, error, retry) on the websites list.
- 229 backend + 30 frontend tests passing; verified live against real sites (single-page, multi-page, SSRF block, tenant isolation, incremental re-crawl).

Out of scope (deferred to Phase 5): semantic chunking, embedding generation, vector storage, duplicate detection across embeddings.

---

# Phase 5 — Knowledge Processing

## Goal

Convert website content into searchable knowledge.

### Tasks

- Semantic chunking
- Metadata generation
- Embedding generation
- Vector storage
- Incremental crawling
- Duplicate detection

### Deliverables

- Knowledge Base

### Status — COMPLETE (August 2026)

The Phase 5 knowledge pipeline is implemented, tested, and verified end-to-end
(ADR-008):

- **Chunking** (`backend/services/knowledge/chunker.py`): dependency-free token
  chunker (regex word/punctuation tokenizer), TRD-aligned defaults
  `KNOWLEDGE_CHUNK_SIZE_TOKENS=700`, `KNOWLEDGE_CHUNK_OVERLAP_TOKENS=100`,
  sentence/paragraph-boundary alignment, and guaranteed-forward window so
  chunking always terminates.
- **Embedding** (`backend/services/knowledge/embedding.py`):
  `GoogleEmbeddingClient` calling `text-embedding-004` through the GenAI async
  SDK — batching (`EMBEDDING_BATCH_SIZE=32`), per-batch exponential backoff with
  full jitter and retry cap (`EMBEDDING_MAX_RETRIES=5`), timeout enforcement,
  usage capture (calls/characters/estimated_tokens/failures) via an optional
  hook, and fail-fast on missing `GEMINI_API_KEY` (`EmbeddingUnavailableError`).
- **Vector storage** (`backend/repositories/vector/`): `VectorRepository`
  Protocol + MongoDB Atlas `$vectorSearch` implementation over the
  `knowledge_chunks` collection (tenant/website pre-filter, Top-5 cosine,
  `index: "default"`, actionable error when the Atlas index is missing).
  Unique `(tenant_id, website_id, document_id, chunk_index)` index makes chunk
  inserts idempotent; all writes/deletes are tenant-scoped.
- **Orchestration** (`backend/services/knowledge/processor.py`):
  `KnowledgeProcessor` binds only Protocols. `process_document` is idempotent —
  skips when the SHA-256 checksum is unchanged and chunks already exist,
  replaces chunks on content change, records a clean state for empty pages, and
  marks `failed` + audits `KNOWLEDGE_FAILED` when embedding errors.
  `process_website_documents` fans documents out as per-document ARQ jobs.
- **Worker** (`backend/workers/jobs/knowledge.py`): `process_document` and
  `process_website_documents` registered in the ARQ task registry; the shared
  `GoogleEmbeddingClient` is injected via `ctx["embedding_client"]` at worker
  startup.
- **Read side**: `KnowledgeChunkRepository` counts and
  `WebsiteOut.knowledge_{status,documents,chunks}` + `last_knowledge_at`
  surface "knowledge status" on the dashboard website cards.
- **Tests**: chunker, embedding-client, processor (incremental skip, replace on
  change, no-content, embedding failure, tenant isolation, fan-out), and worker
  task tests; full backend suite green (263 tests).

Out of scope (deferred to Phase 6): retrieval (question embedding + vector
search), prompt building, Gemini generation, conversation memory. Duplicate
detection across embeddings remains open for the analytics phase.

---

# Phase 6 — RAG Pipeline

## Goal

Generate accurate AI responses.

### Tasks

- Question embedding
- Vector search
- Context retrieval
- Prompt builder
- Gemini integration
- Streaming response
- Conversation memory

### Rules

- Never answer without context.
- Never hallucinate.
- Always retrieve before generation.

### Deliverables

- Working chatbot

---

# Phase 7 — Dashboard

## Goal

Build SaaS dashboard.

### Pages

- Dashboard
- Websites
- Conversations
- Analytics
- Widget
- API Keys
- Profile
- Settings

### Deliverables

- Fully functional dashboard

---

# Phase 8 — Widget SDK

## Goal

Build embeddable chatbot widget.

### Tasks

- Floating launcher
- Chat window
- Streaming UI
- Markdown support
- Suggested questions
- Theme customization
- Responsive design

### Deliverables

- Production widget

---

# Phase 9 — Analytics

## Goal

Track chatbot usage.

### Features

- Daily chats
- Visitor count
- Response time
- Crawl statistics
- Popular questions
- Failed queries

### Deliverables

- Analytics dashboard

---

# Phase 10 — Security Hardening

## Goal

Secure the platform.

### Implement

- RBAC
- Rate limiting
- API validation
- Secure headers
- HTTPS
- CSP
- CORS
- Input sanitization
- Output escaping
- Audit logging
- Secret management

### Protection Against

- XSS
- CSRF
- SSRF
- SQL Injection
- NoSQL Injection
- Prompt Injection
- Brute Force
- DDoS
- API Abuse

### Deliverables

- Security audit passed

---

# Phase 11 — Performance Optimization

## Goal

Optimize performance.

### Tasks

- Redis caching
- Lazy loading
- Query optimization
- Compression
- Image optimization
- Code splitting

### Performance Targets

Dashboard

< 2 seconds

Widget

< 100 KB

API

< 500 ms

---

# Phase 12 — Testing

## Unit Tests

- Backend
- Frontend
- AI Services

## Integration Tests

- APIs
- Authentication
- Chat

## E2E Tests

- Signup
- Login
- Website Setup
- Chat

## Security Tests

- Authentication
- Authorization
- Injection attacks

### Deliverables

90%+ critical path coverage

---

# Phase 13 — Deployment

## Frontend

- Vercel

## Backend

- Render

## Database

- MongoDB Atlas

## Redis

- Upstash

### Tasks

- Configure production environment
- SSL
- Environment variables
- Health checks
- Monitoring

---

# Phase 14 — Monitoring

## Logging

- API Logs
- Crawl Logs
- AI Logs
- Error Logs
- Audit Logs

## Monitoring

- Uptime
- CPU
- Memory
- Queue
- Response Time

Future

- Grafana
- Prometheus
- Sentry

---

# Phase 15 — Documentation

Complete documentation for

- Installation
- Deployment
- API
- Architecture
- Environment Variables
- Troubleshooting
- Contributing

---

# Development Workflow

```text
Project Setup
        ↓
Authentication
        ↓
Website Management
        ↓
Crawler
        ↓
Knowledge Processing
        ↓
Embeddings
        ↓
Vector Search
        ↓
RAG Pipeline
        ↓
Widget
        ↓
Dashboard
        ↓
Analytics
        ↓
Security
        ↓
Testing
        ↓
Deployment
```

---

# Cursor AI Development Workflow

For every phase:

1. Read the relevant documentation.
2. Create architecture.
3. Implement backend.
4. Implement frontend.
5. Write tests.
6. Verify security.
7. Verify performance.
8. Update documentation.
9. Commit changes.
10. Proceed only after all checks pass.

---

# Success Criteria

The project is complete when:

- Users can register and log in securely.
- Websites can be crawled and indexed.
- Knowledge base is generated automatically.
- AI answers only from indexed content.
- Widget can be embedded with one script.
- Dashboard manages all resources.
- Multi-tenant isolation is enforced.
- Security best practices are implemented.
- Performance targets are achieved.
- All tests pass.
- Application is production-ready.

---

# Future Roadmap

- PDF & DOCX Knowledge Base
- Image OCR
- Voice Chat
- Multi-language Support
- WhatsApp Integration
- Slack Integration
- GitHub Repository Chat
- Notion Integration
- Human Handoff
- AI Agents
- MCP Support
- Multi-Model Support (Gemini, GPT, Claude, Grok)

---

# End of Implementation Plan
