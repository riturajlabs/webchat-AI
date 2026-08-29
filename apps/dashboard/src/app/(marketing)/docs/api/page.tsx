import Link from 'next/link';

import {
  Bullets,
  Callout,
  DocHeader,
  DocSection,
  EndpointBadge,
  type EndpointMethod,
  InlineCode,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/api',
  title: 'API reference',
  description:
    'The WebChat AI REST API: websites, widget configuration, knowledge base, conversations, analytics, billing, feedback and API keys.',
});

interface Endpoint {
  method: EndpointMethod;
  path: string;
  description: string;
}

const GROUPS: { title: string; id: string; description?: string; endpoints: Endpoint[] }[] = [
  {
    title: 'Health',
    id: 'health',
    endpoints: [
      { method: 'GET', path: '/api/health/live', description: 'Liveness probe.' },
      {
        method: 'GET',
        path: '/api/health',
        description: 'Liveness probe with dependency status.',
      },
      { method: 'GET', path: '/api/health/ready', description: 'Readiness probe.' },
    ],
  },
  {
    title: 'Websites',
    id: 'websites',
    description: 'Register sites, trigger crawls and manage the widget configuration.',
    endpoints: [
      {
        method: 'POST',
        path: '/api/websites',
        description: 'Register a website and start ingestion (201).',
      },
      {
        method: 'GET',
        path: '/api/websites',
        description: 'List websites for the current tenant.',
      },
      {
        method: 'GET',
        path: '/api/websites/{websiteId}',
        description: 'Website detail and status.',
      },
      {
        method: 'PATCH',
        path: '/api/websites/{websiteId}',
        description: 'Update website details.',
      },
      {
        method: 'DELETE',
        path: '/api/websites/{websiteId}',
        description: 'Remove a website and its data.',
      },
      {
        method: 'POST',
        path: '/api/websites/{websiteId}/crawl',
        description: 'Start a new crawl for the site (202).',
      },
      {
        method: 'GET',
        path: '/api/websites/{websiteId}/widget',
        description: 'Read the widget configuration plus authoritative embed script.',
      },
      {
        method: 'PATCH',
        path: '/api/websites/{websiteId}/widget',
        description: 'Update widget configuration fields.',
      },
    ],
  },
  {
    title: 'Knowledge base',
    id: 'knowledge',
    endpoints: [
      {
        method: 'GET',
        path: '/api/knowledge/websites/{websiteId}/documents',
        description: 'List crawled/embedded documents with their status.',
      },
      {
        method: 'POST',
        path: '/api/knowledge/documents/{documentId}/retry',
        description: 'Re-run embedding for a failed document.',
      },
    ],
  },
  {
    title: 'Crawl jobs',
    id: 'crawl-jobs',
    endpoints: [
      {
        method: 'GET',
        path: '/api/crawl-jobs/{jobId}',
        description: "Poll a crawl job's status and progress.",
      },
      {
        method: 'GET',
        path: '/api/crawl-jobs/{jobId}/stream',
        description: 'Server-sent events stream of live job updates.',
      },
    ],
  },
  {
    title: 'Conversations',
    id: 'conversations',
    endpoints: [
      {
        method: 'GET',
        path: '/api/conversations?{filters}',
        description: 'List conversations (search/status filters supported).',
      },
      {
        method: 'GET',
        path: '/api/conversations/{sessionId}',
        description: 'Fetch one conversation with messages and sources.',
      },
      {
        method: 'DELETE',
        path: '/api/conversations/{sessionId}',
        description: 'Delete a conversation.',
      },
    ],
  },
  {
    title: 'Analytics',
    id: 'analytics',
    description: 'All analytics endpoints accept days plus optional website filters.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/analytics/summary?days={n}',
        description: 'Headline KPIs for the selected window.',
      },
      {
        method: 'GET',
        path: '/api/analytics/overview?days={n}',
        description: 'Aggregated overview metrics.',
      },
      {
        method: 'GET',
        path: '/api/analytics/timeseries?days={n}',
        description: 'Conversations/messages over time.',
      },
      {
        method: 'GET',
        path: '/api/analytics/top-websites?days={n}',
        description: 'Most active websites.',
      },
      {
        method: 'GET',
        path: '/api/analytics/questions?days={n}&limit=10',
        description: 'Most frequent visitor questions.',
      },
      {
        method: 'GET',
        path: '/api/analytics/performance?days={n}',
        description: 'Response-time metrics.',
      },
      {
        method: 'GET',
        path: '/api/analytics/feedback?days={n}',
        description: 'Feedback sentiment breakdown.',
      },
    ],
  },
  {
    title: 'Feedback',
    id: 'feedback',
    endpoints: [
      { method: 'GET', path: '/api/feedback?{filters}', description: 'List feedback entries.' },
      {
        method: 'GET',
        path: '/api/feedback/summary?days={n}',
        description: 'Compact satisfaction summary.',
      },
    ],
  },
  {
    title: 'Billing',
    id: 'billing',
    endpoints: [
      { method: 'GET', path: '/api/billing/plans', description: 'Available plans.' },
      {
        method: 'GET',
        path: '/api/billing/subscription',
        description: 'Current subscription and payment history.',
      },
      { method: 'GET', path: '/api/billing/usage', description: 'Usage against plan limits.' },
      {
        method: 'POST',
        path: '/api/billing/checkout',
        description: 'Create a checkout session for a plan (201).',
      },
    ],
  },
  {
    title: 'API keys',
    id: 'api-keys',
    description: 'Authenticate server-to-server requests. Secrets are shown once at creation time.',
    endpoints: [
      {
        method: 'POST',
        path: '/api/api-keys',
        description: 'Create an API key (201). Secret returned once.',
      },
      { method: 'GET', path: '/api/api-keys', description: 'List API keys.' },
      {
        method: 'DELETE',
        path: '/api/api-keys/{keyId}',
        description: 'Revoke an API key immediately.',
      },
    ],
  },
];

export default function ApiPage() {
  return (
    <div className="flex flex-col gap-8">
      <DocHeader
        breadcrumb="Platform / API reference"
        title="API reference"
        lede="The REST surface behind the dashboard. All requests are JSON over HTTPS against the deployment's API origin and require authentication unless noted."
      />

      <DocSection id="conventions" title="Conventions">
        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">Base URL.</strong> Your deployed API
              origin; the dashboard uses <InlineCode>NEXT_PUBLIC_API_URL</InlineCode>.
            </>,
            <>
              <strong className="font-medium text-foreground">Authentication.</strong>{' '}
              <InlineCode>Authorization: Bearer</InlineCode> token for sessions, API keys for
              server-to-server access.
            </>,
            <>
              <strong className="font-medium text-foreground">Errors.</strong> Structured payload:{' '}
              <InlineCode>{`{ "error": { "code", "message" } }`}</InlineCode>.
            </>,
          ]}
        />
      </DocSection>

      <DocSection
        id="errors"
        title="Error codes"
        description="The HTTP status and machine-readable code returned in the error payload."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Error codes by HTTP status</caption>
            <thead>
              <tr className="border-b text-muted-foreground">
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Status
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  Codes
                </th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  [
                    '400',
                    [
                      'INVALID_URL',
                      'EMBEDDING_UNAVAILABLE',
                      'EMBEDDING_INCOMPATIBLE',
                      'INVALID_QUESTION',
                      'GENERATION_UNAVAILABLE',
                      'SPAM_REJECTED',
                      'INVALID_PAYMENT_SIGNATURE',
                      'PLAN_NOT_PURCHASABLE',
                    ],
                  ],
                  [
                    '401',
                    [
                      'INVALID_CREDENTIALS',
                      'INVALID_TOKEN',
                      'TOKEN_EXPIRED',
                      'TOKEN_REUSE_DETECTED',
                    ],
                  ],
                  [
                    '403',
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
                    '404',
                    [
                      'WEBSITE_NOT_FOUND',
                      'CRAWL_JOB_NOT_FOUND',
                      'DOCUMENT_NOT_FOUND',
                      'SESSION_NOT_FOUND',
                      'WIDGET_NOT_FOUND',
                      'API_KEY_NOT_FOUND',
                      'MESSAGE_NOT_FOUND',
                      'TENANT_NOT_FOUND',
                      'PLAN_NOT_FOUND',
                      'USER_NOT_FOUND',
                    ],
                  ],
                  [
                    '409',
                    [
                      'EMAIL_ALREADY_EXISTS',
                      'WEBSITE_ALREADY_EXISTS',
                      'CRAWL_IN_PROGRESS',
                      'WEBSITE_NOT_READY',
                    ],
                  ],
                  ['422', ['INSUFFICIENT_CONTENT']],
                  [
                    '429',
                    [
                      'ACCOUNT_LOCKED',
                      'AI_QUOTA_EXCEEDED',
                      'RATE_LIMIT_EXCEEDED',
                      'MESSAGE_LIMIT_REACHED',
                      'LIMIT_REACHED',
                    ],
                  ],
                  ['500', ['PROVIDER_CONFIGURATION']],
                  ['501', ['NOT_IMPLEMENTED']],
                  ['502', ['EMBEDDING_FAILED', 'GENERATION_FAILED', 'PAYMENT_PROVIDER_ERROR']],
                  ['503', ['SERVICE_UNAVAILABLE']],
                ] as Array<[string, string[]]>
              ).map(([status, codes]) => (
                <tr key={status} className="border-b last:border-0 align-top">
                  <td className="py-2 pr-3 font-mono text-xs">{status}</td>
                  <td className="py-2">
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
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{`${group.title} endpoints`}</caption>
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Method
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Endpoint
                  </th>
                  <th scope="col" className="py-1.5 font-medium">
                    Description
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.endpoints.map(({ method, path, description }) => (
                  <tr key={`${method} ${path}`} className="border-b last:border-0 align-top">
                    <td className="py-2 pr-3">
                      <EndpointBadge method={method} />
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">{path}</td>
                    <td className="py-2 text-muted-foreground">{description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DocSection>
      ))}

      <DocSection
        id="widget-runtime"
        title="Widget runtime"
        description="Visitor-facing chat traffic."
      >
        <p className="text-sm text-muted-foreground">
          Visitor-facing chat traffic runs on{' '}
          <Link
            href="/docs/embed"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed
          </Link>{' '}
          for how the SDK resolves the public widget API origin.
        </p>
      </DocSection>

      <Callout variant="tip" title="Build on the API">
        Start in the{' '}
        <Link
          href="/docs/quickstart"
          className="font-medium text-blue-600 hover:underline dark:text-blue-400"
        >
          Quickstart
        </Link>{' '}
        to register a site, then use these endpoints to drive crawls, configuration and analytics.
      </Callout>
    </div>
  );
}
