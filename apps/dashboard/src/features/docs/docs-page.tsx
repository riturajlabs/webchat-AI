'use client';

import { BookOpen } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

import { CodeBlock } from './code-block';
import {
  buildEmbedScript,
  buildInitExample,
  buildMountExample,
  DASHBOARD_URL,
  DOCS_WIDGET_ID,
  WIDGET_API_URL,
  WIDGET_SCRIPT_URL,
} from '@/features/widget/embed';

const SCRIPT_TAG = buildEmbedScript(DOCS_WIDGET_ID);
const SCRIPT_TAG_WITH_API = `<script
  src="${WIDGET_SCRIPT_URL}"
  data-widget-id="${DOCS_WIDGET_ID}"
  data-api-base-url="${WIDGET_API_URL}"
  defer
></script>`;
const INIT_EXAMPLE = buildInitExample(DOCS_WIDGET_ID, WIDGET_API_URL);
const MOUNT_EXAMPLE = buildMountExample(DOCS_WIDGET_ID);
const CSP_EXAMPLE = `connect-src 'self' ${WIDGET_API_URL};`;
const INSTALL_COMMAND = `npm install @webchat/widget`;

const CONFIG_OPTIONS: { key: string; values: string; description: string }[] = [
  { key: 'theme', values: 'light | dark | auto', description: 'Color scheme of the widget.' },
  {
    key: 'position',
    values: 'bottom-right | bottom-left',
    description: 'Corner of the viewport where the launcher sits.',
  },
  {
    key: 'primary_color',
    values: '#rrggbb',
    description: 'Primary action color (launcher, send button, header).',
  },
  { key: 'accent_color', values: '#rrggbb', description: 'Secondary accent color.' },
  { key: 'font_size', values: 'sm | md | lg', description: 'Base font size inside the chat.' },
  { key: 'logo_url', values: 'https://…', description: 'Custom logo shown in the header.' },
  { key: 'avatar_url', values: 'https://…', description: 'Assistant avatar image.' },
  {
    key: 'welcome_message',
    values: 'text',
    description: 'Greeting shown above the first message.',
  },
  { key: 'placeholder', values: 'text', description: 'Composer placeholder text.' },
  {
    key: 'suggested_questions',
    values: 'string[] (max 5)',
    description: 'Quick-prompt chips offered to new visitors.',
  },
  {
    key: 'branding',
    values: 'true | false',
    description: 'Show the "Powered by WebChat AI" badge.',
  },
  {
    key: 'dark_mode',
    values: 'true | false',
    description: 'Force the dark theme regardless of the visitor system theme.',
  },
  {
    key: 'auto_open',
    values: 'true | false',
    description: 'Open the chat automatically for new visitors.',
  },
  {
    key: 'enabled',
    values: 'true | false',
    description: 'Hide the widget from the page entirely.',
  },
  {
    key: 'allowed_domains',
    values: 'string[] (max 50)',
    description: 'Origins permitted to embed the widget. Empty = any origin.',
  },
];

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription className="text-sm">{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 p-4 pt-2">{children}</CardContent>
    </Card>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return <h3 className="font-sans text-sm font-medium text-muted-foreground">{children}</h3>;
}

/** Developer documentation for the WebChat AI embeddable widget. */
export function DocsPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <BookOpen aria-hidden="true" className="size-5 text-muted-foreground" />
          <h1 className="font-sans text-2xl font-bold tracking-tight">Developer documentation</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          Add the WebChat AI assistant to any website with a single script tag.
        </p>
      </header>

      <Section
        title="Installation"
        description="Two ways to bring the widget into your site — the hosted script or the SDK package."
      >
        <SubHeading>Option 1 — Hosted script (no build step)</SubHeading>
        <p className="text-sm text-muted-foreground">
          Paste the embed script from your dashboard on{' '}
          <a href={`${DASHBOARD_URL}/widget`} className="text-primary underline">
            Widget → Widget embed code
          </a>
          . No installation required — the bundle is served from{' '}
          <code className="font-mono text-xs">{WIDGET_SCRIPT_URL}</code>.
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy script tag" />
        <SubHeading>Option 2 — SDK package (framework apps)</SubHeading>
        <p className="text-sm text-muted-foreground">
          Install the widget SDK for React, Vue or any bundler-based app:
        </p>
        <CodeBlock code={INSTALL_COMMAND} language="bash" copyLabel="Copy install command" />
      </Section>

      <Section
        title="Script embedding"
        description="The script auto-upgrades from data-widget-id — no init() call required."
      >
        <SubHeading>Basic usage</SubHeading>
        <p className="text-sm text-muted-foreground">
          Add this to your page and the launcher appears once the script has run. The{' '}
          <code className="font-mono text-xs">defer</code> attribute keeps the script from blocking
          page render.
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy embed script" />
        <SubHeading>Overriding the API origin</SubHeading>
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
        <SubHeading>Programmatic usage</SubHeading>
        <p className="text-sm text-muted-foreground">
          For framework apps, import the SDK and call{' '}
          <code className="font-mono text-xs">init()</code>:
        </p>
        <CodeBlock code={INIT_EXAMPLE} language="ts" copyLabel="Copy init() example" />
        <p className="text-sm text-muted-foreground">
          Or mount into an existing element with <code className="font-mono text-xs">mount()</code>:
        </p>
        <CodeBlock code={MOUNT_EXAMPLE} language="ts" copyLabel="Copy mount() example" />
      </Section>

      <Section
        title="Domain allowlist setup"
        description="Restrict which origins may embed your widget."
      >
        <p className="text-sm text-muted-foreground">
          By default a new widget is seeded with the registered website&apos;s hostname, so it can
          only be embedded there. To allow more origins, open{' '}
          <a href={`${DASHBOARD_URL}/widget`} className="text-primary underline">
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
          <li>An empty list allows any origin (the pre-configured default).</li>
        </ul>
        <CodeBlock
          code={`https://example.com     → allowed
https://shop.example.com  → allowed (via *.example.com)
https://evil.example.net  → 403 Forbidden`}
          language="text"
          copyLabel="Copy matching examples"
        />
        <p className="text-sm text-muted-foreground">
          Requests without an <code className="font-mono text-xs">Origin</code> header (curl,
          server-to-server) are not browser embeds and are not restricted by the allowlist.
        </p>
      </Section>

      <Section
        title="Configuration options"
        description="Every field is editable from the dashboard widget builder (PATCH /api/websites/{id}/widget)."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Option</th>
                <th className="py-1.5 pr-3 font-medium">Values</th>
                <th className="py-1.5 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {CONFIG_OPTIONS.map(({ key, values, description }) => (
                <tr key={key} className="border-b last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-xs">{key}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs text-muted-foreground">{values}</td>
                  <td className="py-1.5 text-muted-foreground">{description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Troubleshooting" description="Common issues and how to fix them.">
        <ul className="flex flex-col gap-3 text-sm text-muted-foreground">
          <li>
            <span className="font-medium text-foreground">Widget does not appear.</span> Confirm the
            website is ready and the widget is enabled in the dashboard, then hard refresh your
            page. Config is cached for up to 5 minutes.
          </li>
          <li>
            <span className="font-medium text-foreground">403 Forbidden.</span> The embedding origin
            is not in the allowlist. Add the site&apos;s hostname under{' '}
            <a href={`${DASHBOARD_URL}/widget`} className="text-primary underline">
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
      </Section>

      <Section title="Security notes" description="How the widget is secured by default.">
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
      </Section>
    </div>
  );
}
