import {
  BreadcrumbNav,
  Bullets,
  Callout,
  Checklist,
  DiagramBox,
  DocHeader,
  DocSection,
  InlineCode,
  RelatedDocs,
} from '@/components/marketing/docs-ui';
import { CodeBlock } from '@/features/docs/code-block';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/security',
  title: 'Security, privacy & tenant isolation',
  description:
    'Overview of WebChat AI enterprise security controls: multi-tenant data isolation, origin domain validation, SSRF defense, file upload guards, and CSP directives.',
});

export default function SecurityDocPage() {
  return (
    <div className="flex flex-col gap-8">
      <BreadcrumbNav
        items={[
          { label: 'Documentation', href: '/docs' },
          { label: 'Developer' },
          { label: 'Security' },
        ]}
      />

      <DocHeader
        breadcrumb="Developer / Security & privacy"
        title="Security & isolation"
        lede="WebChat AI is built with multi-tenant data isolation, cryptographic session management, origin validation, SSRF crawler defenses, and strict ingestion bounds."
      />

      <DocSection
        id="tenant-isolation"
        title="Multi-tenant data isolation"
        description="How tenant data boundaries are strictly enforced across storage, search, and retrieval."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          Every organization in WebChat AI is assigned an immutable{' '}
          <InlineCode>tenant_id</InlineCode>. All data structures—including assistant
          configurations, crawled web documents, vector embeddings, file attachments, and
          conversation transcripts—are partitioned by tenant:
        </p>

        <DiagramBox
          title="Tenant Isolation Architecture"
          description="Enforced at every layer from API boundary to storage partitions."
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                LAYER 1
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">Principal Extraction</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Incoming requests authenticate via JWT session or API key, resolving
                principal.tenant_id.
              </p>
            </div>
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                LAYER 2
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">Service Boundary</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Service layer enforces tenant scope. Cross-tenant reads or writes fail before
                database execution.
              </p>
            </div>
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                LAYER 3
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">Database Scoping</p>
              <p className="mt-1 text-xs text-muted-foreground">
                All database queries and vector searches include tenant_id compound indexes.
              </p>
            </div>
            <div className="rounded-lg border border-border/70 p-4 bg-card">
              <span className="font-mono text-xs font-bold text-blue-600 dark:text-blue-400">
                LAYER 4
              </span>
              <p className="mt-1 text-sm font-medium text-foreground">Storage Partitions</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Uploaded files and vector attachments are stored in tenant-isolated namespaces.
              </p>
            </div>
          </div>
        </DiagramBox>
      </DocSection>

      <DocSection
        id="origin-validation"
        title="Origin validation & allowed domains"
        description="Prevent unauthorized third parties from embedding your assistants or consuming your AI quotas."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          By default, every assistant enforces an allowlist of authorized hostnames (
          <InlineCode>allowed_domains</InlineCode>). When the widget initializes on an end-user
          page, the backend validates the incoming <InlineCode>Origin</InlineCode> and{' '}
          <InlineCode>Referer</InlineCode> headers against this allowlist:
        </p>

        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">Exact Domain Match:</strong>{' '}
              Specifying <InlineCode>example.com</InlineCode> allows embedding on{' '}
              <InlineCode>https://example.com</InlineCode>.
            </>,
            <>
              <strong className="font-medium text-foreground">Wildcard Subdomains:</strong>{' '}
              Specifying <InlineCode>*.example.com</InlineCode> authorizes all subdomains (e.g.{' '}
              <InlineCode>docs.example.com</InlineCode>, <InlineCode>app.example.com</InlineCode>).
            </>,
            <>
              <strong className="font-medium text-foreground">Local Development:</strong> In
              non-production environments, requests from <InlineCode>localhost</InlineCode> and{' '}
              <InlineCode>127.0.0.1</InlineCode> are permitted automatically to streamline local
              testing.
            </>,
            <>
              <strong className="font-medium text-foreground">Rejection:</strong> If a disallowed
              domain attempts to mount the widget, the handshake returns{' '}
              <InlineCode>403 WIDGET_ORIGIN_NOT_ALLOWED</InlineCode>.
            </>,
          ]}
        />

        <Callout variant="warning" title="5-Minute Widget Cache Window">
          Public widget configuration (including allowed domains) is cached server-side in Redis for
          up to 300 seconds (5 minutes) with best-effort invalidation upon dashboard updates.
        </Callout>
      </DocSection>

      <DocSection
        id="ssrf-defense"
        title="SSRF crawler defense"
        description="How the ingestion pipeline blocks Server-Side Request Forgery attacks."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          When an assistant is configured to crawl a website, the ingestion crawler performs
          rigorous DNS resolution and IP filtering before dispatching HTTP requests. The crawler
          categorically rejects:
        </p>

        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Blocked IP spaces for SSRF prevention</caption>
            <thead className="bg-muted/50 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3">
                  CIDR Block / Destination
                </th>
                <th scope="col" className="px-4 py-3">
                  Classification
                </th>
                <th scope="col" className="px-4 py-3">
                  Security Rationale
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60 font-mono text-xs">
              <tr>
                <td className="px-4 py-3 text-red-600 dark:text-red-400">127.0.0.0/8, ::1</td>
                <td className="px-4 py-3 font-sans text-foreground">Loopback Address</td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  Blocks requests directed at local host services and internal admin daemons.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-red-600 dark:text-red-400">
                  10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
                </td>
                <td className="px-4 py-3 font-sans text-foreground">RFC 1918 Private Ranges</td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  Blocks scanning of internal VPC networks and private cluster databases.
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-red-600 dark:text-red-400">
                  169.254.0.0/16, 169.254.169.254
                </td>
                <td className="px-4 py-3 font-sans text-foreground">Link-Local / Cloud Metadata</td>
                <td className="px-4 py-3 font-sans text-muted-foreground">
                  Prevents theft of cloud instance IAM credentials and Kubernetes tokens.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection
        id="upload-bounds"
        title="File upload bounds & parsing safety"
        description="Preventing resource exhaustion, memory denial-of-service, and malicious attachments."
      >
        <Checklist
          items={[
            <>
              <strong className="font-medium text-foreground">Strict File Type Whitelist:</strong>{' '}
              Only .pdf, .docx, .md, and .txt files are accepted. Binary executables, scripts, and
              archives (.zip, .tar) are rejected immediately (400 UNSUPPORTED_MEDIA_TYPE).
            </>,
            <>
              <strong className="font-medium text-foreground">Batch & File Size Caps:</strong>{' '}
              Maximum 10 MB per upload batch and maximum 5 files per batch (400 DOCUMENT_TOO_LARGE).
            </>,
            <>
              <strong className="font-medium text-foreground">100-Page PDF Limit:</strong> PDFs
              exceeding 100 pages are rejected to prevent parser CPU starvation and memory spikes.
            </>,
            <>
              <strong className="font-medium text-foreground">Encrypted PDF Rejection:</strong>{' '}
              Password-protected PDFs cannot be safely inspected or chunked and are immediately
              flagged with a helpful user prompt.
            </>,
          ]}
        />
      </DocSection>

      <DocSection
        id="csp-setup"
        title="Content Security Policy (CSP)"
        description="Configuring your site's CSP headers to allow the WebChat AI widget."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          If your web application publishes a strict Content Security Policy, ensure your server
          includes the WebChat AI script and connect origins:
        </p>

        <CodeBlock
          language="http"
          filename="Content-Security-Policy"
          code={`Content-Security-Policy:
  script-src 'self' https://api.webchat.ai;
  connect-src 'self' https://api.webchat.ai;
  font-src 'self' https://fonts.gstatic.com;
  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;`}
        />
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'REST API reference',
            href: '/docs/api',
            description: 'Explore API endpoints and authentication headers.',
          },
          {
            title: 'Embed guide',
            href: '/docs/embed',
            description: 'Learn how to mount the widget and configure domain allowlists.',
          },
          {
            title: 'Troubleshooting',
            href: '/docs/troubleshooting',
            description: 'Diagnose 403 WIDGET_ORIGIN_NOT_ALLOWED and CSRF validation errors.',
          },
        ]}
      />
    </div>
  );
}
