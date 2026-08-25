import type { Metadata } from 'next';
import Link from 'next/link';

import { DocHeader, DocSection, SubHeading } from '@/components/marketing/docs-ui';

export const metadata: Metadata = {
  title: 'API',
  description:
    'The WebChat AI REST API: websites, widget configuration, knowledge base, conversations, analytics, billing and API keys.',
};

interface Endpoint {
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  path: string;
  description: string;
}

const METHOD_STYLES: Record<Endpoint['method'], string> = {
  GET: 'bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400',
  POST: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
  PATCH: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  DELETE: 'bg-red-500/10 text-red-700 dark:bg-red-500/15 dark:text-red-400',
};

const GROUPS: { title: string; description?: string; endpoints: Endpoint[] }[] = [
  {
    title: 'Health',
    endpoints: [
      {
        method: 'GET',
        path: '/api/health',
        description: 'Service and dependency health snapshot.',
      },
    ],
  },
  {
    title: 'Websites',
    description: 'Register sites, trigger crawls and manage the widget configuration.',
    endpoints: [
      {
        method: 'GET',
        path: '/api/websites',
        description: 'List websites for the current tenant.',
      },
      {
        method: 'POST',
        path: '/api/websites',
        description: 'Register a website and start ingestion.',
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
        description: 'Start a new crawl for the site.',
      },
      {
        method: 'GET',
        path: '/api/websites/{websiteId}/widget',
        description: 'Read the widget configuration.',
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
    endpoints: [
      {
        method: 'GET',
        path: '/api/crawl-jobs/{jobId}',
        description: 'Poll a crawl job’s status and progress.',
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
      {
        method: 'GET',
        path: '/api/feedback/summary?days={n}',
        description: 'Compact satisfaction summary.',
      },
    ],
  },
  {
    title: 'Billing',
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
        description: 'Create a checkout session for a plan.',
      },
    ],
  },
  {
    title: 'API keys',
    description: 'Authenticate server-to-server requests. Secrets are shown once at creation time.',
    endpoints: [
      { method: 'GET', path: '/api/api-keys', description: 'List API keys.' },
      { method: 'POST', path: '/api/api-keys', description: 'Create an API key.' },
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
    <div className="flex flex-col gap-6">
      <DocHeader
        title="API reference"
        lede="The REST surface behind the dashboard. All requests are JSON over HTTPS against the deployment's API origin and require authentication unless noted."
      />

      <DocSection title="Conventions">
        <SubHeading>Request format</SubHeading>
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            Base URL: your deployed API origin; the dashboard uses{' '}
            <code className="font-mono text-xs">NEXT_PUBLIC_API_URL</code>.
          </li>
          <li>
            Authentication: <code className="font-mono text-xs">Authorization: Bearer</code> token
            for sessions, API keys for server-to-server access.
          </li>
          <li>
            Errors return a structured payload:{' '}
            <code className="font-mono text-xs">{`{ "error": { "code", "message" } }`}</code>.
          </li>
        </ul>
      </DocSection>

      {GROUPS.map((group) => (
        <DocSection key={group.title} title={group.title} description={group.description}>
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
                      <span
                        className={`inline-block rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold ${METHOD_STYLES[method]}`}
                      >
                        {method}
                      </span>
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

      <DocSection title="Widget runtime">
        <p className="text-sm text-muted-foreground">
          Visitor-facing chat traffic runs on{' '}
          <code className="font-mono text-xs">/api/widget/v1/*</code> under the widget API origin —
          see{' '}
          <Link
            href="/docs/embed"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed
          </Link>{' '}
          for how the SDK resolves it.
        </p>
      </DocSection>
    </div>
  );
}
