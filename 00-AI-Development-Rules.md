# WebChat AI - AI Development Rules

**Version:** 1.0  
**Project Name:** WebChat AI  
**Document Type:** AI Coding Agent Instructions  
**Purpose:** Master development rules for Cursor / Claude Code / AI Coding Agents  
**Author:** Ritu Raj  
**Status:** Active

---

## 1. Purpose

This document defines mandatory rules that every AI coding agent must follow while developing WebChat AI.

The objective is to ensure:
- Production-quality code
- Secure architecture
- Maintainable codebase
- Consistent development decisions
- Scalable system design
- Professional engineering standards

The AI agent must read this document before generating or modifying any code.

---

## 2. Project Vision

WebChat AI is a production-grade, multi-tenant AI SaaS platform that enables users to create website-specific AI assistants using Retrieval-Augmented Generation (RAG).

The system must be:
- Secure
- Scalable
- Modular
- Maintainable
- Cloud-ready
- AI-first

---

## 3. Core Development Principles

The AI agent MUST follow:

### Clean Code
- Write readable code.
- Use meaningful variable names.
- Avoid unnecessary complexity.
- Keep functions small.
- Avoid duplicate logic.

### SOLID Principles
Follow:
- Single Responsibility
- Open/Closed
- Liskov Substitution
- Interface Segregation
- Dependency Inversion

### DRY Principle
Do not repeat code. Create:
- Reusable components
- Shared utilities
- Common services

### KISS Principle
Prefer simple solutions. Avoid unnecessary abstraction.

---

## 4. Architecture Rules

The AI must follow the defined architecture.

### Frontend
**Technology:**
- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui

**Rules:**
- Use TypeScript strictly.
- Avoid JavaScript files.
- Use reusable components.
- Follow feature-based structure.
- Keep UI logic separated from business logic.

### Backend
**Technology:**
- FastAPI
- Python
- MongoDB
- Redis

**Rules:**
- Use async operations.
- Use service layer architecture.
- Use repository pattern.
- Separate business logic from API routes.
- Validate all requests.

---

## 5. Folder Structure Rules

Follow this exact structure:

```text
webchat-ai/
├── apps/
│   ├── dashboard/
│   └── widget/
├── backend/
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── repositories/
│   ├── workers/
│   ├── ai/
│   └── utils/
├── docs/
├── tests/
└── docker/
```

*Never create random folders.*

---

## 6. Backend Rules

### API Layer
API routes should only:
- Receive request
- Validate input
- Call services
- Return response

*Do not write business logic inside routes.*

### Service Layer
Responsible for:
- Business logic
- Processing
- Workflow execution

### Repository Layer
Responsible for:
- Database operations
- External storage
- Vector database operations

### Database
**Rules:**
- Every tenant-owned query must include `tenant_id`.
- Never expose database objects directly.
- Use schemas for validation.
- Create proper indexes.

---

## 7. Multi-Tenant Security Rules

This is mandatory. Every tenant resource must contain:

`tenant_id`

**Examples:**
- Websites
- Knowledge Base
- Conversations
- Analytics
- API Keys

**Never allow:**
`Tenant A ↓ Tenant B Data`

All queries must verify ownership.

---

## 8. Authentication Rules

**Implementation:**
- JWT Access Token
- Refresh Token
- Argon2 Password Hashing

**Rules:**
- Never store plain passwords.
- Never expose tokens.
- Validate sessions.
- Implement logout correctly.

---

## 9. API Security Rules

Every API must include:

### Input Validation
Use:
- Pydantic
- Zod

### Rate Limiting
Protect against:
- Spam
- Abuse
- DDoS

### Authorization
Every protected route requires:
- Authentication
- Permission check
- Tenant validation

---

## 10. Web Security Rules

Implement:
- HTTPS only
- Secure headers
- CORS policy
- CSP
- CSRF protection
- XSS prevention

---

## 11. Scraper Security Rules

Because users submit URLs, the crawler must prevent:

### SSRF
Block:
- `localhost`
- private IP ranges
- internal services

### Resource Abuse
Limit:
- Crawl depth
- Page count
- File size
- Request timeout

### Content Security
Always sanitize:
- HTML
- Scripts
- User-generated content

---

## 12. AI/RAG Development Rules

The AI system must follow:

### Retrieval First
**Flow:**  
`Question` ↓ `Embedding` ↓ `Vector Search` ↓ `Context Retrieval` ↓ `LLM Generation`

*Never call LLM without retrieval.*

### Hallucination Prevention
The model must:
- Answer only from context.
- Say "I don't know" when information is unavailable.
- Never invent facts.

### Prompt Rules
Prompts must be:
- Stored separately.
- Version controlled.
- Easy to update.

---

## 13. Vector Database Rules

Never directly couple application logic with MongoDB Vector Search. 

Use the `VectorRepository` Interface.

**Supported providers:**
- MongoDB Vector Search
- Qdrant
- Pinecone
- Weaviate

---

## 14. Frontend Rules

### Components
Every component should be:
- Reusable
- Typed
- Small
- Testable

### State Management
Avoid unnecessary global state. Use:
- React Query
- Context
- Local state (where appropriate)

### UI Rules
Every page must have:
- Loading state
- Error state
- Empty state
- Success feedback

---

## 15. Widget Development Rules

Widget must be:
- Lightweight
- Framework independent
- Secure
- Responsive

Must support:
- Floating launcher
- Streaming responses
- Markdown
- Mobile screens
- Theme customization

---

## 16. Error Handling Rules

Never silently fail. Every error must:
- Have meaningful message.
- Be logged.
- Return proper status code.
- Help debugging.

---

## 17. Logging Rules

**Log:**
- Errors
- Authentication events
- Security events
- Crawl jobs
- AI failures

**Never log:**
- Passwords
- API secrets
- Private user data

---

## 18. Testing Rules

Every important feature requires tests. Required:

### Backend
- Unit Tests
- API Tests
- Integration Tests

### Frontend
- Component Tests
- User Flow Tests

### AI
- Retrieval Accuracy Tests
- Prompt Evaluation

---

## 19. Git Rules

**Commit messages:**
- `feat:`
- `fix:`
- `docs:`
- `refactor:`
- `test:`
- `security:`

**Examples:**
- `feat: add website crawler service`
- `fix: resolve JWT refresh issue`
- `security: add rate limiting`

---

## 20. Environment Rules

Never hardcode:
- API keys
- Passwords
- Database URLs
- Secrets

Use:
- `.env`
- `.env.example`

---

## 21. Dependency Rules

Before adding a package, check:
- Maintenance
- Security
- Community support
- License

*Avoid unnecessary dependencies.*

---

## 22. Performance Rules

Always consider:
- Database queries
- API response time
- Bundle size
- Memory usage
- AI token usage

Optimize:
- Caching
- Lazy loading
- Pagination
- Background jobs

---

## 23. Documentation Rules

Every major feature must include:
- Purpose
- Architecture
- Usage
- API documentation
- Configuration

---

## 24. AI Agent Workflow

Before coding:
1. Read project documentation.
2. Understand architecture.
3. Plan implementation.
4. Explain changes.
5. Write code.
6. Add tests.
7. Verify security.
8. Update documentation.

---

## 25. Forbidden Practices

The AI agent must NOT:
- ❌ Create duplicate functionality
- ❌ Hardcode secrets
- ❌ Skip validation
- ❌ Ignore errors
- ❌ Mix business logic with UI
- ❌ Bypass security checks
- ❌ Use random architecture decisions
- ❌ Remove tests without reason
- ❌ Add unnecessary dependencies

---

## 26. Definition of Done

A feature is complete only when:
- ✅ Code implemented
- ✅ Tests written
- ✅ Security reviewed
- ✅ Error handling added
- ✅ Documentation updated
- ✅ Performance considered
- ✅ No lint errors
- ✅ Production ready

---

## 27. Final Rule

When uncertain:
1. Follow existing architecture.
2. Prefer security over convenience.
3. Prefer maintainability over shortcuts.
4. Ask before making major architectural changes.

*The AI agent must behave like a senior software engineer building a production SaaS product.*

---

**End of AI Development Rules**