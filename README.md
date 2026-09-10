# 🤖 WebChat AI

### Turn any website into a source-grounded AI assistant.

WebChat AI is a production-ready, multi-tenant AI SaaS platform that turns
website content into an intelligent conversational knowledge base.

Crawl a website, build a retrieval-augmented knowledge base, and give visitors
accurate streaming answers with citations — all through a lightweight,
embeddable chat widget.

<p align="center">
  <strong>🌐 Website → 🕷️ Crawl → 🧠 RAG → 💬 AI Assistant</strong>
</p>

---

## 🚀 Live Product

**Dashboard:**
https://webchat-ai-dashboard.vercel.app

Create an account, crawl a website, configure an AI assistant, and embed it
into your website.

---

## ✨ Why WebChat AI?

Most AI chatbots require manually maintained knowledge bases.

WebChat AI takes a different approach:

> **Your website becomes the knowledge base.**

The platform automatically crawls your website, extracts useful content,
creates embeddings, indexes the content, and uses hybrid retrieval to ground
AI responses in the source material.

### What you get

| Capability                  | Description                                                         |
| --------------------------- | ------------------------------------------------------------------- |
| 🕷️ Smart Website Crawling   | HTTP-first crawling with targeted JavaScript rendering fallback     |
| 🧠 Source-Grounded RAG      | Hybrid vector + keyword retrieval with RRF fusion                   |
| 📚 Automatic Knowledge Base | Website pages are cleaned, chunked, embedded, and indexed           |
| 💬 Streaming AI Chat        | Real-time responses using Server-Sent Events                        |
| 🔗 Source Citations         | Answers can reference the original website content                  |
| 🏢 Multi-Tenant SaaS        | Isolated organizations, users, knowledge bases, and usage           |
| 🎨 Embeddable Widget        | Add the assistant to a website with a simple script                 |
| 💳 Billing & Usage          | Plans, subscriptions, usage metering, and token budgets             |
| 🔐 Security First           | SSRF protection, CSRF, rate limiting, tenant isolation, and more    |
| 📊 Admin & Observability    | Metrics, structured logs, health checks, and administrative tooling |

---

## 🎯 Built For

WebChat AI can be used for:

- 🎓 Universities and educational institutions
- 📚 Documentation websites
- 💻 SaaS products
- 🛒 E-commerce websites
- 🏢 Business websites
- 🛠️ Customer support portals
- 📖 Knowledge bases
- 🧑‍💻 Product documentation
- 🌐 Service-based websites

---

# ⚡ How It Works

At a high level:

```text
┌─────────────────────┐
│      Your Website   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Smart Crawler     │
│ HTTP-first + JS     │
│ fallback            │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Clean + Chunk       │
│ Website content     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Embedding Provider  │
│ Gemini / Jina /     │
│ Cohere              │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ MongoDB Knowledge   │
│ Base + Vectors      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Hybrid RAG          │
│ Vector + Keyword    │
│ + RRF + Reranking   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ LLM Generation      │
│ Gemini / Groq /     │
│ OpenRouter          │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Answer + Citations  │
└─────────────────────┘
```

---

# 🧠 RAG Pipeline

Every visitor question goes through a controlled retrieval and generation
pipeline:

```text
Visitor Question
       │
       ▼
Query Classification
       │
       ▼
Conversational Rewrite
       │
       ▼
Hybrid Retrieval
 ┌─────┴─────┐
 ▼           ▼
Vector     Keyword
Search     Search
 └─────┬─────┘
       ▼
    RRF Fusion
       │
       ▼
 Optional Reranking
       │
       ▼
Context Assembly
       │
       ▼
Streaming Generation
       │
       ▼
Confidence + Faithfulness Checks
       │
   ┌───┴────┐
   ▼        ▼
 Answer   Abstain
   │
   ▼
Source Citations
```

### Retrieval features

- Vector search
- Keyword retrieval
- Reciprocal Rank Fusion (RRF)
- Source diversification
- Optional reranking
- Query classification
- Conversational query rewriting
- Confidence gating
- Context budgeting
- Duplicate prevention
- Corpus-version-aware caching
- Prompt-injection detection
- Cross-tenant isolation
- Faithfulness checks
- Safe abstention when the knowledge base cannot support an answer

The system is designed to prefer:

> **"I don't have enough information to answer that."**

over generating an unsupported answer.

---

# 🕷️ Website Crawler

WebChat AI uses an **HTTP-first hybrid crawler** designed to maximize useful
website coverage while keeping crawler resource usage practical.

## Crawl pipeline

### 1. Discover

The crawler starts from configured entry points and discovers:

- Website links
- Sitemap URLs
- Priority paths
- Same-origin pages

Breadth-first traversal and page budgets prevent uncontrolled crawling.

### 2. Guard

Every destination passes SSRF and URL validation.

The crawler:

- Allows HTTP/HTTPS destinations
- Enforces same-origin crawling
- Respects `robots.txt`
- Rejects unsafe destinations
- Canonicalizes URLs
- Applies crawl limits

### 3. Fetch

The crawler is **HTTP-first**.

```text
             ┌───────────────┐
             │   Web Page    │
             └───────┬───────┘
                     │
                     ▼
              HTTP Fetch
                     │
              ┌──────┴──────┐
              │             │
          Useful HTML     JS Shell
              │             │
              ▼             ▼
           Extract       Playwright
                          Fallback
```

Static and server-rendered pages avoid launching Chromium.

JavaScript rendering is used only when the page contains strong evidence that
HTTP extraction is insufficient.

### 4. Clean and chunk

Extracted HTML is cleaned and converted into useful text.

Content is then:

- Normalized
- Deduplicated
- Chunked
- Token-budgeted
- Overlapped where appropriate
- Filtered when effectively empty

### 5. Embed

Chunks are converted into embeddings using the configured embedding provider.

The system keeps a consistent embedding space for a corpus to avoid mixing
incompatible vector representations.

### 6. Persist

Tenant-scoped documents and chunks are persisted in MongoDB together with
their embedding identity and metadata.

Failed ingestion work is retried with backoff and can be quarantined after
repeated failures.

---

# 🏗️ Architecture

## Application architecture

```mermaid
flowchart LR

    subgraph Customer["Customer Website"]
        WIDGET["WebChat AI Widget<br/>One-line Embed"]
    end

    subgraph Platform["WebChat AI Platform"]
        DASH["Dashboard<br/>Next.js"]
        API["API<br/>FastAPI"]
        WORKER["Worker<br/>ARQ + Crawler"]
    end

    subgraph Data["Data Layer"]
        MONGO[("MongoDB<br/>Documents + Vectors")]
        REDIS[("Redis<br/>Cache + Queue + Rate Limits")]
    end

    subgraph AI["AI Providers"]
        GEN["Generation<br/>Gemini · Groq · OpenRouter"]
        EMB["Embeddings<br/>Gemini · Jina · Cohere"]
    end

    WIDGET -->|"SSE / Widget API"| API
    DASH -->|"Same-origin /api proxy"| API

    API --> MONGO
    API --> REDIS

    WORKER --> MONGO
    WORKER --> REDIS

    API --> GEN
    API --> EMB
    WORKER --> EMB

    WORKER -->|"HTTP crawl + targeted JS rendering"| Customer
```

---

# ☁️ Production Deployment

WebChat AI's current production architecture is split between **Vercel** and
**Railway**.

```text
                         Internet
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
     ┌─────────────────┐        ┌─────────────────┐
     │     Vercel      │        │     Railway     │
     │                 │        │                 │
     │ Dashboard       │───────▶│ FastAPI API     │
     │ Widget          │        │ ARQ Worker       │
     └─────────────────┘        └────────┬────────┘
                                         │
                              ┌──────────┴──────────┐
                              │                     │
                              ▼                     ▼
                       ┌─────────────┐       ┌─────────────┐
                       │  MongoDB    │       │    Redis    │
                       │   Atlas     │       │   Managed   │
                       └─────────────┘       └─────────────┘
```

### Production services

| Service       | Platform        | Responsibility                                       |
| ------------- | --------------- | ---------------------------------------------------- |
| Dashboard     | Vercel          | Next.js dashboard and web application                |
| Widget        | Vercel          | Production embeddable widget bundle                  |
| API           | Railway         | FastAPI API, authentication, RAG, billing, streaming |
| Worker        | Railway         | ARQ jobs, website crawling, ingestion, embeddings    |
| Database      | Managed MongoDB | Documents, chunks, vectors, tenant data              |
| Cache / Queue | Managed Redis   | Caching, rate limits, job queue, provider health     |

### Production principles

- HTTPS everywhere
- Same-origin dashboard API proxy
- Secure authentication cookies
- Production environment validation
- Immutable deployment artifacts where applicable
- Health checks
- Structured JSON logging
- Prometheus metrics
- CI security gates
- Secret scanning
- Container security scanning

See the full production runbook:

[`docs/deployment/README.md`](docs/deployment/README.md)

---

# 🧩 Monorepo Structure

```text
webchat-AI/
│
├── apps/
│   ├── dashboard/          # Next.js dashboard + tenant application
│   └── widget/             # Framework-independent embeddable widget
│
├── backend/
│   ├── api/                # FastAPI routes and dependencies
│   ├── core/               # Configuration and application infrastructure
│   ├── repositories/       # Data access
│   ├── schemas/            # Pydantic schemas
│   ├── services/           # Business logic
│   ├── workers/            # ARQ background jobs
│   └── ...
│
├── packages/
│   └── themes/             # Shared widget themes
│
├── docs/                   # Architecture, ADRs, deployment and audits
├── docker/                 # Dockerfiles and Compose configuration
├── scripts/                # Development and operational helpers
├── tests/                  # Automated test suites
│
├── package.json
├── pnpm-workspace.yaml
├── pyproject.toml
└── uv.lock
```

Each major area contains its own README with deeper implementation details.

---

# 🛠️ Tech Stack

| Layer         | Technology                                        |
| ------------- | ------------------------------------------------- |
| Backend       | Python 3.13 · FastAPI · Pydantic v2               |
| Database      | MongoDB / Motor                                   |
| Cache & Queue | Redis · ARQ                                       |
| Generation    | Google Gemini · Groq · OpenRouter                 |
| Embeddings    | Gemini · Jina · Cohere                            |
| Dashboard     | Next.js 15 · React 19 · Tailwind CSS v4           |
| Widget        | TypeScript · Vite · Shadow DOM                    |
| Sanitization  | DOMPurify                                         |
| Markdown      | GFM-compatible rendering                          |
| Crawling      | HTTPX · BeautifulSoup · Playwright                |
| Containers    | Docker · Docker Compose                           |
| CI/CD         | GitHub Actions (CI/validation) · Vercel · Railway |
| Observability | Prometheus · Structured JSON logs                 |
| Deployment    | Vercel + Railway                                  |

---

# 💬 Embeddable Widget

WebChat AI is designed to be embedded into an existing website with minimal
integration work.

## Basic integration

```html
<script
  src="https://webchat-ai-widget.vercel.app/webchat-widget.iife.min.js"
  data-widget-id="YOUR_WIDGET_ID"
  defer
></script>
```

The widget can automatically initialize from the `data-widget-id` attribute.

For advanced usage, the Widget SDK also supports programmatic initialization,
mounting, theming, CSP configuration, and other integration options.

See:

[`apps/widget/README.md`](apps/widget/README.md)

---

# 🎨 Widget Features

The widget provides:

- Streaming AI responses
- Markdown rendering
- Tables
- Source citations
- Citation links
- Shadow DOM isolation
- Curated themes
- CSS custom-property theming
- Offline/error handling
- Responsive layout
- Accessibility-focused UI
- Safe HTML rendering
- Automatic initialization
- Framework-independent integration

---

# 🔐 Security

Security is treated as a core part of the platform rather than an afterthought.

### Authentication

- JWT authentication
- Secure refresh cookies
- `SameSite=Strict`
- CSRF protection
- Email verification
- Password reset protections
- Login lockout
- Rate limiting
- Password hashing with Argon2id

### Application security

- Tenant isolation
- SSRF protection
- Request validation
- High-risk port blocking
- Secure host validation
- Production environment validation
- Secret scanning
- PII redaction
- Prompt-injection detection
- Injection tracking
- Safe failure and abstention

### Infrastructure

- Read-only production containers where appropriate
- Temporary filesystems
- Container image scanning
- CI security gates
- Production configuration validation
- Secure CORS configuration

---

# 🏢 Multi-Tenancy

WebChat AI is designed as a multi-tenant SaaS platform.

Tenant boundaries are maintained across:

```text
User
  │
  ▼
Tenant / Workspace
  │
  ├── Websites
  │
  ├── Knowledge Base
  │     ├── Documents
  │     └── Chunks / Vectors
  │
  ├── Conversations
  │
  ├── Usage
  │
  ├── API Keys
  │
  └── Billing
```

Tenant-scoped access is enforced through the backend rather than relying only
on frontend filtering.

---

# 💳 Billing & Usage

The platform includes SaaS billing infrastructure with support for:

- Subscription plans
- Usage metering
- LLM token budgets
- Payment provider abstraction
- Razorpay
- Stripe
- Mock provider for development/testing
- Payment webhooks
- Idempotent subscription activation

Payment and billing logic is isolated from the core RAG pipeline.

---

# 🧪 Quality & Testing

The project maintains a comprehensive automated test suite covering:

- Authentication
- Account security
- Authorization
- Tenant isolation
- RAG retrieval
- Retrieval accuracy
- Embeddings
- Provider routing
- Generation fallback
- Website crawling
- SSRF protection
- Widget API
- Widget rendering
- Billing
- Observability
- Configuration
- Infrastructure behavior

Latest full backend verification:

```text
2266+ tests passing
```

Additional frontend and widget test suites are maintained separately.

## Local verification

```bash
# Backend
./scripts/check-backend.sh

# Dashboard / frontend
pnpm lint
pnpm typecheck
pnpm build
pnpm test

# Secret scanning
./scripts/check-secrets.sh
```

See:

[`tests/README.md`](tests/README.md)

---

# 🚀 Quick Start

## Prerequisites

- Node.js >= 20
- pnpm >= 9
- Python 3.13
- uv
- Docker
- Docker Compose

## 1. Clone

```bash
git clone https://github.com/riturajlabs/webchat-AI.git
cd webchat-AI
```

## 2. Configure environment

```bash
cp .env.development .env
```

The development environment is configured for the local Docker services.

## 3. Start the stack

```bash
docker compose \
  --env-file .env.development \
  -f docker/compose.yml \
  up --build
```

## 4. Install frontend dependencies

```bash
pnpm install
```

## 5. Start the dashboard

```bash
pnpm dev:dashboard
```

Dashboard:

```text
http://localhost:3000
```

The backend and worker can also be started using the repository's development
scripts.

See:

- [`backend/README.md`](backend/README.md)
- [`apps/dashboard/README.md`](apps/dashboard/README.md)
- [`docker/README.md`](docker/README.md)

---

# ⚙️ Configuration

Environment variables are documented in:

```text
.env.example
```

Important production configuration includes:

```text
ENVIRONMENT
DEBUG
JWT_SECRET
CORS_ORIGINS
ALLOWED_HOSTS
PUBLIC_BASE_URL
NEXT_PUBLIC_API_URL
NEXT_PUBLIC_BACKEND_API_URL
VITE_WIDGET_API_BASE_URL
GENERATION_PROVIDER_ORDER
EMBEDDING_PROVIDER_ORDER
EMBEDDING_DIMENSIONS
CRAWL_HTTP_FIRST
CRAWL_MAX_CONCURRENT
EMBEDDING_MAX_CONCURRENT_BATCHES
```

Production configuration validation intentionally fails fast on unsafe
configuration such as weak secrets, loopback production origins, missing
provider credentials, or unsupported mock payment configuration.

---

# 📚 Documentation

| Document                                                   | Purpose                       |
| ---------------------------------------------------------- | ----------------------------- |
| [`docs/README.md`](docs/README.md)                         | Documentation index           |
| [`docs/deployment/README.md`](docs/deployment/README.md)   | Production deployment runbook |
| [`backend/README.md`](backend/README.md)                   | Backend architecture and API  |
| [`apps/dashboard/README.md`](apps/dashboard/README.md)     | Dashboard development         |
| [`apps/widget/README.md`](apps/widget/README.md)           | Widget SDK                    |
| [`packages/themes/README.md`](packages/themes/README.md)   | Widget themes                 |
| [`docker/README.md`](docker/README.md)                     | Containers and Compose        |
| [`tests/README.md`](tests/README.md)                       | Testing strategy              |
| [`scripts/README.md`](scripts/README.md)                   | Development and operations    |
| [`00-AI-Development-Rules.md`](00-AI-Development-Rules.md) | AI development rules          |

The `docs/` directory also contains architecture decision records (ADRs),
implementation documentation, deployment material, and historical audit
reports.

---

# 🗺️ Roadmap

The platform is continuously evolving.

Potential future areas include:

- Advanced analytics
- Additional AI providers
- Additional embedding providers
- More crawling strategies
- Improved retrieval evaluation
- Additional integrations
- Expanded widget customization
- More enterprise controls

---

# 🤝 Contributing

Contributions are welcome when they align with the project's architecture,
security model, and Definition of Done.

Before submitting changes:

```bash
./scripts/check-backend.sh
pnpm lint
pnpm typecheck
pnpm build
pnpm test
./scripts/check-secrets.sh
```

Please read the repository development rules before making architectural or
cross-cutting changes.

For security vulnerabilities, avoid opening a public issue. Use the project's
private security reporting channel instead.

---

# 📄 License

**Proprietary — All Rights Reserved.**

See the repository license information for usage and distribution terms.

---

<p align="center">
  <strong>WebChat AI</strong>
  <br />
  Turn any website into an AI-powered knowledge assistant.
</p>
