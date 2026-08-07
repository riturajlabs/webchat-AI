# WebChat AI - Backend Schema

**Version:** 1.0  
**Project Name:** WebChat AI  
**Document Type:** Backend Database Schema  
**Database:** MongoDB Atlas + Vector Search  
**Author:** Ritu Raj  
**Status:** Draft  
**Last Updated:** August 2026

---

# 1. Overview

WebChat AI follows a **multi-tenant architecture** where every tenant has complete data isolation.

All collections that store customer data **must include `tenant_id`**.

The database should be optimized for:

- Fast vector search
- Scalability
- Security
- Multi-tenancy
- Analytics
- Audit logging

---

# 2. Collections Overview

| Collection | Purpose |
|------------|----------|
| users | Authentication & User Accounts |
| tenants | Tenant Information |
| websites | Registered Websites |
| widgets | Widget Configuration |
| knowledge_chunks | RAG Knowledge Base |
| crawl_jobs | Crawl Queue Status |
| chat_sessions | Visitor Sessions |
| messages | Individual Chat Messages |
| analytics | Dashboard Analytics |
| api_keys | API Key Management |
| audit_logs | Security & Activity Logs |

---

# 3. users Collection

Stores authenticated dashboard users.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "name": "John Doe",
  "email": "john@example.com",
  "password_hash": "argon2_hash",
  "role": "owner",
  "email_verified": true,
  "status": "active",
  "created_at": "ISODate",
  "updated_at": "ISODate",
  "last_login": "ISODate"
}
```

Indexes

```
email (Unique)

tenant_id
```

---

# 4. tenants Collection

Stores organization information.

```json
{
  "_id": "UUID",
  "company_name": "ABC Pvt Ltd",
  "plan": "free",
  "status": "active",
  "created_at": "ISODate"
}
```

Future

- Billing
- Team Members
- Subscription
- Usage Limits

---

# 5. websites Collection

Stores websites connected by tenants.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "url": "https://example.com",
  "name": "Example Website",
  "status": "ready",
  "pages_indexed": 125,
  "last_crawled_at": "ISODate",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

Status

- Pending
- Crawling
- Processing
- Ready
- Failed

Indexes

```
tenant_id

url
```

---

# 6. widgets Collection

Stores widget configuration.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "website_id": "UUID",
  "widget_id": "UUID",
  "theme": "light",
  "position": "bottom-right",
  "primary_color": "#2563eb",
  "welcome_message": "Hi! How can I help you?",
  "branding": true,
  "enabled": true,
  "created_at": "ISODate"
}
```

Indexes

```
widget_id (Unique)

tenant_id
```

---

# 7. knowledge_chunks Collection

Stores semantic chunks and embeddings.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "website_id": "UUID",
  "source_url": "https://example.com/about",
  "page_title": "About Us",
  "chunk_index": 12,
  "text_chunk": "...",
  "embedding": [],
  "metadata": {
    "heading": "About Company",
    "language": "en"
  },
  "created_at": "ISODate"
}
```

Vector Index

```
embedding
```

Indexes

```
tenant_id

website_id

source_url
```

---

# 8. crawl_jobs Collection

Tracks crawling process.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "website_id": "UUID",
  "status": "running",
  "pages_total": 250,
  "pages_completed": 120,
  "started_at": "ISODate",
  "completed_at": null,
  "error_message": null
}
```

Status

- Pending
- Running
- Completed
- Failed

Indexes

```
tenant_id

status
```

---

# 9. chat_sessions Collection

Stores visitor sessions.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "website_id": "UUID",
  "session_id": "UUID",
  "visitor_id": "anonymous",
  "started_at": "ISODate",
  "last_activity": "ISODate"
}
```

Indexes

```
session_id (Unique)

tenant_id
```

---

# 10. messages Collection

Stores conversation history.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "session_id": "UUID",
  "role": "user",
  "content": "What services do you provide?",
  "sources": [],
  "response_time": 1.4,
  "created_at": "ISODate"
}
```

Role

- user
- assistant
- system

Indexes

```
tenant_id

session_id
```

---

# 11. analytics Collection

Stores analytics.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "date": "2026-08-01",
  "total_messages": 400,
  "unique_visitors": 180,
  "avg_response_time": 1.8,
  "successful_answers": 380,
  "failed_answers": 20
}
```

Indexes

```
tenant_id

date
```

---

# 12. api_keys Collection

Stores API keys.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "name": "Production",
  "key_prefix": "wk_live",
  "hashed_secret": "encrypted",
  "last_used": "ISODate",
  "status": "active",
  "created_at": "ISODate"
}
```

Never store raw API keys.

Indexes

```
tenant_id

key_prefix
```

---

# 13. audit_logs Collection

Stores security events.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "user_id": "UUID",
  "action": "LOGIN",
  "ip_address": "...",
  "user_agent": "...",
  "created_at": "ISODate"
}
```

Examples

- Login
- Logout
- Website Added
- Website Deleted
- Widget Updated
- API Key Created

Indexes

```
tenant_id

created_at
```

---

# 14. Relationships

```text
Tenant
│
├── Users
├── Websites
│     ├── Widgets
│     ├── Knowledge Chunks
│     ├── Crawl Jobs
│
├── Chat Sessions
│     └── Messages
│
├── Analytics
├── API Keys
└── Audit Logs
```

---

# 15. MongoDB Indexes

Required Indexes

```
users.email (Unique)

widgets.widget_id (Unique)

chat_sessions.session_id (Unique)

knowledge_chunks.embedding (Vector Index)

knowledge_chunks.tenant_id

messages.session_id

analytics.date

crawl_jobs.status
```

---

# 16. Data Retention

| Collection | Retention |
|------------|-----------|
| Audit Logs | 1 Year |
| Analytics | Unlimited |
| Chat Sessions | 90 Days (Configurable) |
| Crawl Jobs | 30 Days |
| Knowledge Base | Until Deleted |
| Websites | Until Deleted |

---

# 17. Security Rules

- Every query **must include `tenant_id`**.
- Never expose password hashes.
- Never expose embeddings through public APIs.
- Encrypt sensitive fields.
- Validate every Object ID.
- Use server-side authorization only.
- Store passwords using **Argon2**.
- Store API keys as hashed values.
- Use HTTPS for all database communications.

---

# 18. Backup Strategy

- Daily automatic backups
- Point-in-time recovery
- Soft delete for important collections
- Disaster recovery plan

---

# 19. Future Collections

Reserved for future versions.

- feedback
- billing
- subscriptions
- invoices
- notifications
- team_members
- webhooks
- integrations
- ai_models
- feature_flags

---

# 20. Definition of Done

The backend schema is complete when:

- Multi-tenant isolation is enforced.
- Vector search is configured.
- Required indexes are created.
- Relationships are maintained.
- Sensitive data is encrypted.
- API keys are securely stored.
- Audit logging is enabled.
- Collections are optimized for scalability.
- Database supports production workloads.

---

# End of Backend Schema