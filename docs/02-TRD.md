# WebChat AI - Technical Requirements Document (TRD)

**Version:** 1.0  
**Project Name:** WebChat AI  
**Document Type:** Technical Requirements Document (TRD)  
**Architecture Style:** Cloud-Native Multi-Tenant SaaS with Retrieval-Augmented Generation (RAG)  
**Author:** Ritu Raj  
**Status:** Draft  
**Last Updated:** August 2026

---

# 1. Technical Overview

WebChat AI is a production-ready, cloud-native, multi-tenant SaaS platform that enables users to create an AI-powered chatbot for their websites through zero-code integration.

The platform automatically crawls website content, processes it into semantic chunks, generates embeddings, stores them in a vector database, and serves context-aware responses using Retrieval-Augmented Generation (RAG).

The architecture is designed with scalability, security, maintainability, and performance as primary objectives.

---

# 2. Architecture Overview

```text
                     +--------------------+
                     |   Next.js Dashboard |
                     +----------+---------+
                                |
                                |
                          HTTPS / REST
                                |
                                ▼
                  +---------------------------+
                  |      FastAPI Backend      |
                  +------------+--------------+
                               |
      +------------------------+-------------------------+
      |                        |                         |
      ▼                        ▼                         ▼
 Authentication         Chat Service            Ingestion Service
      |                        |                         |
      |                        |                         |
      ▼                        ▼                         ▼
 JWT/Auth              RAG Pipeline              Playwright Worker
                               |
                               ▼
                       MongoDB Atlas
                 (Database + Vector Search)
                               |
                               ▼
                     Google Gemini 2.5 Flash
```

---

# 3. Technology Stack

## Frontend

| Technology      | Purpose              |
| --------------- | -------------------- |
| Next.js 15      | Dashboard Framework  |
| React 19        | UI Library           |
| TypeScript      | Type Safety          |
| Tailwind CSS    | Styling              |
| shadcn/ui       | UI Components        |
| React Query     | API State Management |
| React Hook Form | Forms                |
| Zod             | Validation           |
| Axios           | HTTP Client          |

---

## Backend

| Technology  | Purpose              |
| ----------- | -------------------- |
| FastAPI     | REST API             |
| Python 3.13 | Backend Language     |
| Uvicorn     | ASGI Server          |
| Pydantic v2 | Validation           |
| Motor       | Async MongoDB Driver |
| Celery      | Background Jobs      |
| Redis       | Queue & Cache        |

---

## AI Stack

| Technology                | Purpose           |
| ------------------------- | ----------------- |
| LangGraph                 | AI Workflow       |
| LangChain                 | RAG Components    |
| Gemini 2.5 Flash          | LLM               |
| Google Text Embedding-004 | Embeddings        |
| MongoDB Vector Search     | Similarity Search |

---

## Web Crawling

| Technology    | Purpose              |
| ------------- | -------------------- |
| Playwright    | Dynamic Rendering    |
| BeautifulSoup | HTML Parsing         |
| Readability   | Content Extraction   |
| lxml          | Fast HTML Processing |

---

## Database

| Technology            | Purpose          |
| --------------------- | ---------------- |
| MongoDB Atlas         | Primary Database |
| MongoDB Vector Search | Embedding Search |
| Redis                 | Cache & Queue    |

---

## Hosting

| Component             | Platform      |
| --------------------- | ------------- |
| Frontend              | Vercel        |
| Backend               | Render        |
| Database              | MongoDB Atlas |
| Redis                 | Upstash Redis |
| File Storage (Future) | Cloudinary    |

---

# 4. System Components

## Dashboard

Responsibilities

- Authentication
- Website Management
- Widget Configuration
- Analytics
- Chat History
- Settings

---

## Authentication Service

Responsibilities

- Signup
- Login
- JWT
- Refresh Tokens
- Password Reset
- Email Verification

---

## Ingestion Service

Responsibilities

- Website Crawling
- Content Cleaning
- Chunking
- Embedding Generation
- Knowledge Base Updates

---

## Chat Service

Responsibilities

- Receive Questions
- Retrieve Context
- Generate AI Responses
- Stream Responses
- Save Conversations

---

## Analytics Service

Responsibilities

- Usage Tracking
- Chat Metrics
- Performance Metrics
- Dashboard Statistics

---

# 5. AI Pipeline

```text
Website URL
      │
      ▼
Playwright Crawl
      │
      ▼
HTML Cleaning
      │
      ▼
Content Extraction
      │
      ▼
Semantic Chunking
      │
      ▼
Embedding Generation
      │
      ▼
MongoDB Vector Storage
```

---

### Chat Flow

```text
User Question
      │
      ▼
Generate Embedding
      │
      ▼
Vector Search
      │
      ▼
Retrieve Context
      │
      ▼
Prompt Builder
      │
      ▼
Gemini 2.5 Flash
      │
      ▼
Streaming Response
```

---

# 6. Chunking Strategy

Chunk Type

- Semantic Chunking

Chunk Size

- 500–800 tokens

Overlap

- 100 tokens

Metadata Stored

- Source URL
- Page Title
- Heading
- Crawl Time
- Chunk Number

---

# 7. Retrieval Strategy

Current Version

- Dense Vector Search

Future Version

- Hybrid Search (Vector + Keyword)
- Reranking
- Context Compression

Top K

- Retrieve Top 5 chunks

Similarity

- Cosine Similarity

---

# 8. Prompt Engineering

System Prompt

- AI must answer only from retrieved context.

Developer Prompt

- Never guess information.
- Never fabricate answers.
- Refuse unsupported questions.

Fallback

If context is unavailable:

> "I couldn't find that information in the website's knowledge base."

---

# 9. API Architecture

REST API

Example Modules

```
/api/auth
/api/websites
/api/chat
/api/widget
/api/analytics
/api/settings
/api/admin
```

Response Format

```json
{
  "success": true,
  "message": "Success",
  "data": {}
}
```

Error Format

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request"
  }
}
```

---

# 10. Security Architecture

## Authentication

- JWT Access Token
- Refresh Token Rotation
- Argon2 Password Hashing

---

## Authorization

- Role-Based Access Control (RBAC)
- Tenant Isolation
- Permission Middleware

---

## API Security

- Rate Limiting
- Request Validation
- API Key Validation
- Signed Widget Requests
- Input Sanitization

---

## Web Security

- HTTPS Only
- Secure Cookies
- CORS
- CSP
- HSTS
- X-Frame-Options
- X-Content-Type-Options

---

## Attack Protection

Protect against:

- XSS
- CSRF
- SSRF
- SQL Injection
- NoSQL Injection
- Prompt Injection
- Brute Force
- DDoS
- API Abuse

---

## Secret Management

Never store secrets in source code.

Use

- Environment Variables
- Secret Manager
- Encrypted Storage

---

# 11. Multi-Tenant Architecture

Each tenant has isolated resources.

Isolation includes:

- Knowledge Base
- Conversations
- Widget
- Analytics
- API Keys

Every request must include

- tenant_id
- widget_id

No cross-tenant access is allowed.

---

# 12. Performance Requirements

Dashboard Load

- < 2 seconds

API Response

- < 500 ms (excluding AI generation)

AI Response

- First token < 3 seconds

Vector Search

- < 300 ms

Concurrent Users

- Minimum 500+

---

# 13. Scalability Strategy

Support

- Horizontal Backend Scaling
- Background Workers
- Redis Queue
- CDN Assets
- Stateless API Servers

Future

- Load Balancer
- Auto Scaling

---

# 14. Logging & Monitoring

Logging

- API Logs
- Error Logs
- Authentication Logs
- Crawl Logs

Monitoring

- Health Checks
- Performance Metrics
- Queue Status
- AI Latency
- Database Metrics

Future

- OpenTelemetry
- Grafana
- Prometheus
- Sentry

---

# 15. Backup & Recovery

- Daily MongoDB Backup
- Automatic Recovery
- Point-in-Time Restore
- Audit Logs
- Soft Delete

---

# 16. Coding Standards

Frontend

- Strict TypeScript
- Reusable Components
- Feature-based Folder Structure

Backend

- Async First
- Modular Services
- Dependency Injection
- Repository Pattern

General

- SOLID Principles
- DRY
- KISS
- Meaningful Naming
- Comprehensive Error Handling

---

# 17. AI Development Rules

The AI coding agent must follow these rules:

- Build production-ready code only.
- Never use placeholder implementations.
- Follow the architecture defined in this document.
- Validate all inputs.
- Write secure APIs.
- Keep services modular.
- Do not hardcode secrets.
- Write reusable components.
- Generate clean documentation.
- Add unit tests for critical logic.
- Do not proceed to the next module until the current one is complete and tested.

---

# 18. Definition of Done

The technical implementation is considered complete when:

- Frontend and backend communicate successfully.
- Website crawling works reliably.
- Embeddings are generated and stored.
- RAG pipeline retrieves accurate context.
- AI responds only from website knowledge.
- Widget integration functions correctly.
- Multi-tenant isolation is enforced.
- Security checks pass.
- Performance targets are achieved.
- All critical tests pass successfully.

---

# End of TRD
