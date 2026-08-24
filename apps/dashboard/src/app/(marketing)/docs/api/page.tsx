import type { Metadata } from 'next';
import Link from 'next/link';

import { CodeBlock } from '@/features/docs/code-block';
import { API_ENDPOINTS, DASHBOARD_URL } from '@/features/docs/content';

import { DocsShell, DocSection } from '../_components/docs-shell';

export const metadata: Metadata = {
  title: 'API',
  description:
    'WebChat AI REST API: manage websites, conversations, analytics and API keys programmatically.',
};

const CURL_EXAMPLE = `curl https://api.webchatai.example/api/websites \\
  -H "Authorization: Bearer wc_your_api_key"`;

export default function ApiPage() {
  return (
    <DocsShell active="/docs/api">
      <header className="flex flex-col gap-3">
        <h1 className="font-sans text-3xl font-bold tracking-tight">API</h1>
        <p className="max-w-2xl text-balance text-muted-foreground">
          The platform exposes a tenant-scoped REST API under{' '}
          <code className="font-mono text-xs">https://api.webchatai.example/api</code>. The
          visitor-facing chat transport (streaming SSE) is used by the embed script automatically —
          you never call it directly.
        </p>
      </header>

      <DocSection
        title="Authentication"
        description="Every request needs a bearer token bound to your tenant."
      >
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            Dashboard sessions use short-lived JWT access tokens (refresh handled by the app).
          </li>
          <li>
            Server-to-server integrations use an API key minted in{' '}
            <a
              href={`${DASHBOARD_URL}/api-keys`}
              className="text-primary underline"
              rel="noreferrer noopener"
            >
              API Keys
            </a>
            . Keys look like <code className="font-mono text-xs">wc_…</code> and are shown once at
            creation — store them safely.
          </li>
        </ul>
        <CodeBlock code={CURL_EXAMPLE} language="bash" copyLabel="Copy curl example" />
        <p className="text-sm text-muted-foreground">
          API keys carry per-key rate limits and a full audit trail, so a runaway integration can
          never exhaust your interactive quota.
        </p>
      </DocSection>

      <DocSection
        title="Endpoints"
        description="Core management surface. All routes are scoped to the authenticated tenant."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Method</th>
                <th className="py-1.5 pr-3 font-medium">Path</th>
                <th className="py-1.5 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {API_ENDPOINTS.map(({ method, path, description }) => (
                <tr key={method + path} className="border-b last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-xs">{method}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs">{path}</td>
                  <td className="py-1.5 text-muted-foreground">{description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection title="Conventions" description="Behavior shared across the surface.">
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            Errors return a consistent JSON envelope; authentication failures are{' '}
            <code className="font-mono text-xs">401</code>, cross-tenant access is{' '}
            <code className="font-mono text-xs">404</code> to avoid enumeration.
          </li>
          <li>
            List endpoints are paginated with cursor parameters and support search filters where
            noted.
          </li>
          <li>Mutations are audit-logged; deletes are permanent once confirmed.</li>
        </ul>
      </DocSection>

      <p className="text-sm text-muted-foreground">
        Widget appearance fields referenced by these endpoints are documented in{' '}
        <Link href="/docs/configuration" className="text-primary underline">
          Configuration
        </Link>
        .
      </p>
    </DocsShell>
  );
}
