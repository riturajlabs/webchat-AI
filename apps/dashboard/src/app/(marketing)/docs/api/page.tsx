import {
  BreadcrumbNav,
  Bullets,
  Callout,
  DocHeader,
  DocSection,
  EndpointBadge,
  type EndpointMethod,
  InlineCode,
  RelatedDocs,
} from '@/components/marketing/docs-ui';
import { CodeBlock } from '@/features/docs/code-block';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/api',
  title: 'REST API reference',
  description:
    'Comprehensive WebChat AI REST API documentation with authenticated curl examples, request/response JSON schemas, endpoints, and error codes.',
});

interface Endpoint {
  method: EndpointMethod;
  path: string;
  description: string;
}

const GROUPS: { title: string; id: string; description?: string; endpoints: Endpoint[] }[] = [
  {
    title: 'Health & System',
    id: 'health',
    description: 'Probes for container orchestration and uptime monitoring.',
    endpoints: [
      { method: 'GET', path: '/api/health/live', description: 'Lightweight liveness probe (200).' },
      {
        method: 'GET',
        path: '/api/health',
        description: 'Comprehensive health check reporting database and cache connectivity.',
      },
      {
        method: 'GET',
        path: '/api/health/ready',
        description: 'Readiness probe for load balancers.',
      },
    ],
  },
  {
    title: 'Websites & Assistants',
    id: 'websites',
    description: 'Register assistants, configure ingestion modes, and trigger background crawls.',
    endpoints: [
      {
        method: 'POST',
        path: '/api/websites',
        description: 'Register a new website or document-only assistant (201).',
      },
      {
        method: 'GET',
        path: '/api/websites',
        description: 'List all registered assistants for the authenticated tenant.',
      },
      {
        method: 'GET',
        path: '/api/websites/{websiteId}',
        description: 'Get assistant metadata, crawl status, and knowledge chunk counts.',
      },
      {
        method: 'PATCH',
        path: '/api/websites/{websiteId}',
        description: 'Update assistant name, root URL, or source mode.',
      },
      {
        method: 'DELETE',
        path: '/api/websites/{websiteId}',
        description: 'Permanently remove an assistant and all associated documents/vectors.',
      },
      {
        method: 'POST',
        path: '/api/websites/{websiteId}/crawl',
        description: 'Trigger an asynchronous web crawl job for the root URL (202).',
      },
    ],
  },
  {
    title: 'Knowledge Base & Documents',
    id: 'knowledge',
    description:
      'Upload files (.pdf, .docx, .md, .txt), monitor chunking, and retry failed embeddings.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/knowledge/websites/{websiteId}/documents',
        description: 'List documents for an assistant with processing statuses and summaries.',
      },
      {
        method: 'POST',
        path: '/api/knowledge/websites/{websiteId}/documents/upload',
        description: 'Upload up to 5 documents (max 10 MB total) via multipart/form-data (201).',
      },
      {
        method: 'POST',
        path: '/api/knowledge/documents/{documentId}/retry',
        description: 'Re-queue text extraction and embedding generation for a failed document.',
      },
      {
        method: 'DELETE',
        path: '/api/knowledge/documents/{documentId}',
        description: 'Permanently delete a document, its extracted text, and vector embeddings.',
      },
    ],
  },
  {
    title: 'Crawl Jobs',
    id: 'crawl-jobs',
    description: 'Track background sitemap discovery and page extraction jobs.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/crawl-jobs/{jobId}',
        description: 'Poll crawl job status, pages discovered, and pages indexed.',
      },
      {
        method: 'GET',
        path: '/api/crawl-jobs/{jobId}/stream',
        description: 'Server-Sent Events (SSE) stream providing real-time crawl event updates.',
      },
    ],
  },
  {
    title: 'Widget Configuration',
    id: 'widget',
    description: 'Manage visual appearance, theme presets, font families, and domain allowlists.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/websites/{websiteId}/widget',
        description: 'Fetch the active widget configuration and authoritative embed snippet.',
      },
      {
        method: 'PATCH',
        path: '/api/websites/{websiteId}/widget',
        description: 'Update theme preset, custom colors, font, bot branding, and allowed domains.',
      },
    ],
  },
  {
    title: 'Conversations',
    id: 'conversations',
    description: 'Access visitor conversation history, source citations, and latency telemetry.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/conversations',
        description: 'List visitor conversations with filtering by website, query, and status.',
      },
      {
        method: 'GET',
        path: '/api/conversations/{sessionId}',
        description: 'Retrieve full conversation transcript, token metrics, and cited URLs.',
      },
      {
        method: 'DELETE',
        path: '/api/conversations/{sessionId}',
        description: 'Permanently delete a visitor conversation session and messages.',
      },
    ],
  },
  {
    title: 'Analytics & Reporting',
    id: 'analytics',
    description: 'Aggregated metrics, query frequency, response time histograms, and feedback.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/analytics/summary?days={n}',
        description: 'Headline KPIs including total messages, sessions, response times, and costs.',
      },
      {
        method: 'GET',
        path: '/api/analytics/overview?days={n}',
        description: 'Aggregated overview metrics comparing against prior window.',
      },
      {
        method: 'GET',
        path: '/api/analytics/timeseries?days={n}',
        description: 'Daily message and active conversation timeseries data.',
      },
      {
        method: 'GET',
        path: '/api/analytics/top-websites?days={n}',
        description: 'Activity rankings across registered assistants in your account.',
      },
      {
        method: 'GET',
        path: '/api/analytics/questions?days={n}&limit=10',
        description: 'Most frequently asked visitor questions and satisfaction ratings.',
      },
      {
        method: 'GET',
        path: '/api/analytics/performance?days={n}',
        description: 'Response time percentile breakdowns (p50, p90, p99).',
      },
      {
        method: 'GET',
        path: '/api/analytics/feedback?days={n}',
        description: 'Sentiment breakdown of helpful vs unhelpful responses.',
      },
    ],
  },
  {
    title: 'Feedback',
    id: 'feedback',
    description: 'Visitor sentiment scores and verbatim user comments.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/feedback',
        description: 'List recent visitor feedback entries.',
      },
      {
        method: 'GET',
        path: '/api/feedback/summary?days={n}',
        description: 'Compact positive vs negative satisfaction percentage summary.',
      },
    ],
  },
  {
    title: 'Billing & Plans',
    id: 'billing',
    description: 'Plan catalog, quota consumption, invoices, and checkout sessions.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/billing/plans',
        description: 'List available subscription plans.',
      },
      {
        method: 'GET',
        path: '/api/billing/subscription',
        description: 'Get current active subscription and payment history.',
      },
      {
        method: 'GET',
        path: '/api/billing/usage',
        description: 'Current month usage vs plan limits.',
      },
      {
        method: 'POST',
        path: '/api/billing/checkout',
        description: 'Create a Stripe/payment checkout session for tier upgrades (201).',
      },
    ],
  },
  {
    title: 'API Keys',
    id: 'api-keys',
    description: 'Generate and revoke API keys for headless server-to-server operations.',
    endpoints: [
      {
        method: 'POST',
        path: '/api/api-keys',
        description: 'Create a new scoped API key (201). Secret is displayed only once.',
      },
      {
        method: 'GET',
        path: '/api/api-keys',
        description: 'List existing API keys with last-used timestamps.',
      },
      {
        method: 'DELETE',
        path: '/api/api-keys/{keyId}',
        description: 'Instantly revoke an API key.',
      },
    ],
  },
];

export default function ApiPage() {
  return (
    <div className="flex flex-col gap-8">
      <BreadcrumbNav
        items={[
          { label: 'Documentation', href: '/docs' },
          { label: 'Developer' },
          { label: 'API reference' },
        ]}
      />

      <DocHeader
        breadcrumb="Developer / REST API reference"
        title="REST API reference"
        lede="The authoritative WebChat AI programmatic surface. All requests use JSON over HTTPS and execute with strict multi-tenant isolation."
      />

      <DocSection id="conventions" title="Conventions & authentication">
        <p className="text-sm leading-relaxed text-muted-foreground">
          The WebChat AI API accepts JSON request payloads and returns JSON responses. Timestamps
          are formatted according to ISO 8601 (<InlineCode>YYYY-MM-DDTHH:MM:SSZ</InlineCode>).
        </p>

        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">Base URL:</strong> The API origin
              configured for your deployment. For dashboard clients, this is defined by{' '}
              <InlineCode>NEXT_PUBLIC_API_URL</InlineCode>.
            </>,
            <>
              <strong className="font-medium text-foreground">
                Bearer Token (Browser Sessions):
              </strong>{' '}
              Passed in the <InlineCode>Authorization: Bearer &lt;jwt_access_token&gt;</InlineCode>{' '}
              header.
            </>,
            <>
              <strong className="font-medium text-foreground">API Key (Server-to-Server):</strong>{' '}
              Passed in the <InlineCode>X-API-Key: &lt;secret_key&gt;</InlineCode> header for
              backend integration.
            </>,
            <>
              <strong className="font-medium text-foreground">CSRF Protection:</strong> Mutating
              browser requests (<InlineCode>POST</InlineCode>, <InlineCode>PATCH</InlineCode>,{' '}
              <InlineCode>DELETE</InlineCode>) must supply the <InlineCode>x-csrf-token</InlineCode>{' '}
              header.
            </>,
          ]}
        />
      </DocSection>

      <DocSection id="examples" title="Common workflows & curl examples">
        <div className="flex flex-col gap-6">
          <div>
            <h3 className="font-semibold text-foreground text-sm mb-2">
              1. Register an assistant (Website or Uploads)
            </h3>
            <p className="text-xs text-muted-foreground mb-3">
              Create a new assistant in <InlineCode>website</InlineCode>,{' '}
              <InlineCode>files</InlineCode> (upload-only), or <InlineCode>mixed</InlineCode> mode.
            </p>
            <CodeBlock
              language="bash"
              filename="create-assistant.sh"
              code={`curl -X POST "https://api.webchat.ai/api/websites" \\
  -H "Authorization: Bearer $ACCESS_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "Acme Docs Assistant",
    "url": "https://docs.acme.com",
    "source_mode": "mixed"
  }'`}
            />
            <p className="text-xs text-muted-foreground mt-2 mb-1 font-medium">
              Response (201 Created):
            </p>
            <CodeBlock
              language="json"
              filename="website-created.json"
              code={`{
  "id": "673f4a12bc90ef1234567890",
  "tenant_id": "tenant_98765",
  "name": "Acme Docs Assistant",
  "url": "https://docs.acme.com",
  "source_mode": "mixed",
  "status": "pending",
  "pages_indexed": 0,
  "widget_id": "wgt_ab8901cd",
  "knowledge_status": "empty",
  "knowledge_documents": 0,
  "knowledge_chunks": 0,
  "created_at": "2026-09-16T12:00:00Z",
  "updated_at": "2026-09-16T12:00:00Z"
}`}
            />
          </div>

          <div>
            <h3 className="font-semibold text-foreground text-sm mb-2">
              2. Upload documents to Knowledge Base
            </h3>
            <p className="text-xs text-muted-foreground mb-3">
              Upload up to 5 files (<InlineCode>.pdf</InlineCode>, <InlineCode>.docx</InlineCode>,{' '}
              <InlineCode>.md</InlineCode>, <InlineCode>.txt</InlineCode>) totaling under 10 MB.
            </p>
            <CodeBlock
              language="bash"
              filename="upload-documents.sh"
              code={`curl -X POST "https://api.webchat.ai/api/knowledge/websites/673f4a12bc90ef1234567890/documents/upload" \\
  -H "Authorization: Bearer $ACCESS_TOKEN" \\
  -F "files=@spec-sheet.pdf" \\
  -F "files=@faq-guide.docx"`}
            />
            <p className="text-xs text-muted-foreground mt-2 mb-1 font-medium">
              Response (201 Created):
            </p>
            <CodeBlock
              language="json"
              filename="upload-response.json"
              code={`{
  "website_id": "673f4a12bc90ef1234567890",
  "uploaded": [
    {
      "id": "doc_101",
      "website_id": "673f4a12bc90ef1234567890",
      "file_name": "spec-sheet.pdf",
      "file_size_bytes": 1048576,
      "mime_type": "application/pdf",
      "status": "pending",
      "char_count": 0
    },
    {
      "id": "doc_102",
      "website_id": "673f4a12bc90ef1234567890",
      "file_name": "faq-guide.docx",
      "file_size_bytes": 262144,
      "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "status": "pending",
      "char_count": 0
    }
  ]
}`}
            />
          </div>

          <div>
            <h3 className="font-semibold text-foreground text-sm mb-2">3. Trigger website crawl</h3>
            <p className="text-xs text-muted-foreground mb-3">
              Initiates crawler discovery starting from the registered root URL.
            </p>
            <CodeBlock
              language="bash"
              filename="trigger-crawl.sh"
              code={`curl -X POST "https://api.webchat.ai/api/websites/673f4a12bc90ef1234567890/crawl" \\
  -H "Authorization: Bearer $ACCESS_TOKEN"`}
            />
            <p className="text-xs text-muted-foreground mt-2 mb-1 font-medium">
              Response (202 Accepted):
            </p>
            <CodeBlock
              language="json"
              filename="crawl-accepted.json"
              code={`{
  "job_id": "crawl_89f029",
  "website_id": "673f4a12bc90ef1234567890",
  "status": "queued",
  "pages_discovered": 1,
  "pages_indexed": 0,
  "started_at": "2026-09-16T12:05:00Z"
}`}
            />
          </div>
        </div>
      </DocSection>

      <DocSection
        id="errors"
        title="HTTP status & error codes"
        description="Structured error codes returned in the standard response envelope: { error: { code, message } }."
      >
        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Error codes by HTTP status</caption>
            <thead className="bg-muted/50 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3">
                  Status
                </th>
                <th scope="col" className="px-4 py-3">
                  Codes
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {(
                [
                  [
                    '400 Bad Request',
                    [
                      'INVALID_URL',
                      'EMBEDDING_UNAVAILABLE',
                      'EMBEDDING_INCOMPATIBLE',
                      'INVALID_QUESTION',
                      'GENERATION_UNAVAILABLE',
                      'SPAM_REJECTED',
                      'DOCUMENT_TOO_LARGE',
                      'UNSUPPORTED_MEDIA_TYPE',
                    ],
                  ],
                  [
                    '401 Unauthorized',
                    [
                      'INVALID_CREDENTIALS',
                      'INVALID_TOKEN',
                      'TOKEN_EXPIRED',
                      'TOKEN_REUSE_DETECTED',
                    ],
                  ],
                  [
                    '403 Forbidden',
                    [
                      'ACCOUNT_SUSPENDED',
                      'EMAIL_NOT_VERIFIED',
                      'FORBIDDEN',
                      'CSRF_FAILED',
                      'WIDGET_DISABLED',
                      'WIDGET_ORIGIN_NOT_ALLOWED',
                      'WIDGET_DOMAIN_NOT_CONFIGURED',
                    ],
                  ],
                  [
                    '404 Not Found',
                    [
                      'WEBSITE_NOT_FOUND',
                      'CRAWL_JOB_NOT_FOUND',
                      'DOCUMENT_NOT_FOUND',
                      'SESSION_NOT_FOUND',
                      'WIDGET_NOT_FOUND',
                      'API_KEY_NOT_FOUND',
                      'MESSAGE_NOT_FOUND',
                      'TENANT_NOT_FOUND',
                    ],
                  ],
                  [
                    '409 Conflict',
                    [
                      'EMAIL_ALREADY_EXISTS',
                      'WEBSITE_ALREADY_EXISTS',
                      'CRAWL_IN_PROGRESS',
                      'WEBSITE_NOT_READY',
                    ],
                  ],
                  ['422 Unprocessable', ['INSUFFICIENT_CONTENT', 'VALIDATION_ERROR']],
                  [
                    '429 Too Many Requests',
                    [
                      'AI_QUOTA_EXCEEDED',
                      'RATE_LIMIT_EXCEEDED',
                      'MESSAGE_LIMIT_REACHED',
                      'LIMIT_REACHED',
                    ],
                  ],
                  ['500 Internal Error', ['PROVIDER_CONFIGURATION']],
                  [
                    '502 Bad Gateway',
                    ['EMBEDDING_FAILED', 'GENERATION_FAILED', 'PAYMENT_PROVIDER_ERROR'],
                  ],
                  ['503 Unavailable', ['SERVICE_UNAVAILABLE']],
                ] as Array<[string, string[]]>
              ).map(([status, codes]) => (
                <tr key={status} className="align-top">
                  <td className="px-4 py-3 font-mono text-xs font-semibold text-foreground whitespace-nowrap">
                    {status}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {codes.map((code) => (
                        <InlineCode key={code}>{code}</InlineCode>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DocSection>

      {GROUPS.map((group) => (
        <DocSection
          key={group.title}
          id={group.id}
          title={group.title}
          description={group.description}
        >
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{`${group.title} endpoints`}</caption>
              <thead className="bg-muted/50 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th scope="col" className="px-4 py-3">
                    Method
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Endpoint Path
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Description
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {group.endpoints.map(({ method, path, description }) => (
                  <tr key={`${method} ${path}`} className="align-top">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <EndpointBadge method={method} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs font-medium text-foreground whitespace-nowrap">
                      {path}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground text-xs">{description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DocSection>
      ))}

      <Callout variant="tip" title="Building Headless Integrations">
        If you are building custom chat interfaces or automated ETL pipelines, generate an API Key
        in your dashboard settings and authenticate requests with the{' '}
        <InlineCode>X-API-Key</InlineCode> header.
      </Callout>

      <RelatedDocs
        links={[
          {
            title: 'Security & origin validation',
            href: '/docs/security',
            description: 'Learn about domain allowlists, CSRF protection, and SSRF defense.',
          },
          {
            title: 'Widget embed guide',
            href: '/docs/embed',
            description: 'Integrate the client widget on React, Next.js, or HTML sites.',
          },
          {
            title: 'Troubleshooting guide',
            href: '/docs/troubleshooting',
            description: 'Common API error codes and debugging recipes.',
          },
        ]}
      />
    </div>
  );
}
