import type { Metadata } from 'next';
import Link from 'next/link';

import { CodeBlock } from '@/features/docs/code-block';
import {
  ALLOWLIST_EXAMPLE,
  CSP_EXAMPLE,
  DASHBOARD_URL,
  INIT_EXAMPLE,
  INSTALL_COMMAND,
  MOUNT_EXAMPLE,
  SCRIPT_TAG,
  SCRIPT_TAG_WITH_API,
  WIDGET_SCRIPT_URL,
} from '@/features/docs/content';

import { DocsShell, DocSection } from '../_components/docs-shell';

export const metadata: Metadata = {
  title: 'Embed',
  description:
    'Embed the WebChat AI widget with the hosted script tag or the SDK package, and secure it with your domain allowlist.',
};

export default function EmbedPage() {
  return (
    <DocsShell active="/docs/embed">
      <header className="flex flex-col gap-3">
        <h1 className="font-sans text-3xl font-bold tracking-tight">Embed</h1>
        <p className="max-w-2xl text-balance text-muted-foreground">
          Two ways to bring the widget into your site — the hosted script or the SDK package.
        </p>
      </header>

      <DocSection
        id="installation"
        title="Installation"
        description="Pick one: the hosted script needs no build step; the SDK suits bundler-based apps."
      >
        <h3 className="text-sm font-medium">Option 1 — Hosted script (recommended)</h3>
        <p className="text-sm text-muted-foreground">
          Paste the embed script from your dashboard on{' '}
          <a
            href={`${DASHBOARD_URL}/widget`}
            className="text-primary underline"
            rel="noreferrer noopener"
          >
            Widget → Widget embed code
          </a>
          . No installation required — the bundle is served from{' '}
          <code className="font-mono text-xs">{WIDGET_SCRIPT_URL}</code>.
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy script tag" />
        <h3 className="text-sm font-medium">Option 2 — SDK package</h3>
        <p className="text-sm text-muted-foreground">
          Install the widget SDK for React, Vue or any bundler-based app:
        </p>
        <CodeBlock code={INSTALL_COMMAND} language="bash" copyLabel="Copy install command" />
      </DocSection>

      <DocSection
        id="embedding"
        title="Script embedding"
        description="The script auto-upgrades from data-widget-id — no init() call required."
      >
        <h3 className="text-sm font-medium">Basic usage</h3>
        <p className="text-sm text-muted-foreground">
          Add this to your page and the launcher appears once the script has run. The{' '}
          <code className="font-mono text-xs">defer</code> attribute keeps the script from blocking
          page render.
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy embed script" />
        <h3 className="text-sm font-medium">Overriding the API origin</h3>
        <p className="text-sm text-muted-foreground">
          The bundle ships with the SaaS API baked in. Only set{' '}
          <code className="font-mono text-xs">data-api-base-url</code> when you proxy or self-host
          the widget API.
        </p>
        <CodeBlock
          code={SCRIPT_TAG_WITH_API}
          language="html"
          copyLabel="Copy script tag with API override"
        />
        <h3 className="text-sm font-medium">Programmatic usage</h3>
        <p className="text-sm text-muted-foreground">
          For framework apps, import the SDK and call{' '}
          <code className="font-mono text-xs">init()</code>:
        </p>
        <CodeBlock code={INIT_EXAMPLE} language="ts" copyLabel="Copy init() example" />
        <p className="text-sm text-muted-foreground">
          Or mount into an existing element with <code className="font-mono text-xs">mount()</code>:
        </p>
        <CodeBlock code={MOUNT_EXAMPLE} language="ts" copyLabel="Copy mount() example" />
      </DocSection>

      <DocSection
        id="allowlist"
        title="Domain allowlist setup"
        description="Restrict which origins may embed your widget."
      >
        <p className="text-sm text-muted-foreground">
          By default a new widget is seeded with the registered website&apos;s hostname, so it can
          only be embedded there. To allow more origins, open{' '}
          <a
            href={`${DASHBOARD_URL}/widget`}
            className="text-primary underline"
            rel="noreferrer noopener"
          >
            Widget → Allowed domains
          </a>{' '}
          and add bare hostnames.
        </p>
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            <code className="font-mono text-xs">example.com</code> allows exactly that host (any
            scheme or port).
          </li>
          <li>
            <code className="font-mono text-xs">*.example.com</code> allows the host and every
            subdomain.
          </li>
          <li>
            <code className="font-mono text-xs">*</code> allows any origin (not recommended).
          </li>
          <li>
            An empty list blocks embeds (the widget stays offline) until you add at least one
            domain.
          </li>
        </ul>
        <CodeBlock code={ALLOWLIST_EXAMPLE} language="text" copyLabel="Copy matching examples" />
        <p className="text-sm text-muted-foreground">
          Requests without an <code className="font-mono text-xs">Origin</code> header (curl,
          server-to-server) are not browser embeds and are not restricted by the allowlist.
        </p>
      </DocSection>

      <DocSection
        id="security"
        title="Security notes"
        description="How the widget is secured by default."
      >
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">No secrets in the embed.</span> The widget
            authenticates with short-lived, server-issued session tokens — never with the widget
            secret.
          </li>
          <li>
            <span className="font-medium text-foreground">Origin allowlist.</span> The backend
            verifies the embedding page&apos;s <code className="font-mono text-xs">Origin</code>{' '}
            against <code className="font-mono text-xs">allowed_domains</code> on every public
            widget request.
          </li>
          <li>
            <span className="font-medium text-foreground">Rate limits.</span> Per-widget,
            per-visitor and per-IP budgets bound abuse of sessions, chat and feedback.
          </li>
          <li>
            <span className="font-medium text-foreground">Anonymous by design.</span> The visitor
            identifier is a non-PII cookie value; no localStorage or fingerprinting.
          </li>
          <li>
            <span className="font-medium text-foreground">Spam filtering.</span> Incoming messages
            are screened before they reach the assistant pipeline.
          </li>
        </ul>
      </DocSection>

      <DocSection
        id="troubleshooting"
        title="Troubleshooting"
        description="Common issues and how to fix them."
      >
        <ul className="flex flex-col gap-3 text-sm text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">Widget does not appear.</span> Confirm the
            website is ready and the widget is enabled in the dashboard, then hard refresh your
            page. Config is cached for up to 5 minutes.
          </li>
          <li>
            <span className="font-medium text-foreground">403 Forbidden.</span> The embedding origin
            is not in the allowlist. Add the site&apos;s hostname under{' '}
            <a
              href={`${DASHBOARD_URL}/widget`}
              className="text-primary underline"
              rel="noreferrer noopener"
            >
              Widget → Allowed domains
            </a>
            .
          </li>
          <li>
            <span className="font-medium text-foreground">
              Requests blocked by a Content-Security-Policy.
            </span>{' '}
            Allow the API origin in your connect-src directive:
            <CodeBlock code={CSP_EXAMPLE} language="text" copyLabel="Copy CSP directive" />
          </li>
          <li>
            <span className="font-medium text-foreground">
              &quot;Can&apos;t reach the assistant&quot;.
            </span>{' '}
            A network failure, mid-stream drop, or connection refused. Check the API endpoint and
            your firewall.
          </li>
          <li>
            <span className="font-medium text-foreground">&quot;Message limit reached&quot;.</span>{' '}
            The visitor hit a per-session or rate limit. Try again later.
          </li>
        </ul>
      </DocSection>

      <p className="text-sm text-muted-foreground">
        Appearance and behavior options are covered in{' '}
        <Link href="/docs/configuration" className="text-primary underline">
          Configuration
        </Link>
        .
      </p>
    </DocsShell>
  );
}
