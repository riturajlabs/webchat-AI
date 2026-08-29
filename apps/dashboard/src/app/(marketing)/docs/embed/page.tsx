import Link from 'next/link';

import { CodeBlock } from '@/features/docs/code-block';
import { Tabs } from '@/features/docs/docs-client';
import {
  ALLOWLIST_EXAMPLE,
  CSP_EXAMPLE,
  INIT_EXAMPLE,
  INSTALL_COMMAND,
  MOUNT_EXAMPLE,
  SCRIPT_TAG,
  SCRIPT_TAG_WITH_API,
  WIDGET_SCRIPT_URL,
} from '@/features/docs/content';
import {
  Bullets,
  Callout,
  DocHeader,
  DocSection,
  InlineCode,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/embed',
  title: 'Embed',
  description:
    'Embed the WebChat AI widget: hosted script tag, SDK init()/mount() usage, API origin overrides and domain allowlists.',
});

export default function EmbedPage() {
  return (
    <div className="flex flex-col gap-8">
      <DocHeader
        breadcrumb="Customization / Embed"
        title="Embed"
        lede="Two ways to bring the widget into your site — the hosted script or the SDK package — plus domain control and troubleshooting."
      />

      <DocSection id="hosted-script" title="Hosted script (no build step)">
        <Callout variant="info" title="Fastest path">
          No installation required — the bundle is served from{' '}
          <InlineCode>{WIDGET_SCRIPT_URL}</InlineCode>.
        </Callout>
        <p className="text-sm text-muted-foreground">
          Paste the embed script from your dashboard on{' '}
          <strong className="font-medium text-foreground">Widget &rarr; Embed code</strong>.
        </p>
        <CodeBlock
          code={SCRIPT_TAG}
          language="html"
          filename="index.html"
          copyLabel="Copy script tag"
        />

        <h2 id="api-origin" className="scroll-mt-24 text-lg font-semibold tracking-tight">
          Overriding the API origin
        </h2>
        <p className="text-sm text-muted-foreground">
          The bundle ships with the SaaS API baked in. Only set{' '}
          <InlineCode>data-api-base-url</InlineCode> when you proxy or self-host the widget API.
        </p>
        <CodeBlock
          code={SCRIPT_TAG_WITH_API}
          language="html"
          filename="index.html"
          copyLabel="Copy script tag with API override"
        />
      </DocSection>

      <DocSection
        id="sdk-package"
        title="SDK package (framework apps)"
        description="For React, Vue or any bundler-based app."
      >
        <CodeBlock
          code={INSTALL_COMMAND}
          language="bash"
          filename="terminal"
          copyLabel="Copy install command"
        />

        <Tabs
          defaultValue="init"
          tabs={[
            {
              label: 'init()',
              value: 'init',
              content: (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground">
                    Import the SDK and render the widget with <InlineCode>init()</InlineCode>:
                  </p>
                  <CodeBlock
                    code={INIT_EXAMPLE}
                    language="ts"
                    filename="app.ts"
                    copyLabel="Copy init() example"
                  />
                </div>
              ),
            },
            {
              label: 'mount()',
              value: 'mount',
              content: (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground">
                    Or mount into an existing element with <InlineCode>mount()</InlineCode>:
                  </p>
                  <CodeBlock
                    code={MOUNT_EXAMPLE}
                    language="ts"
                    filename="app.ts"
                    copyLabel="Copy mount() example"
                  />
                </div>
              ),
            },
          ]}
        />
      </DocSection>

      <DocSection
        id="domains"
        title="Domain allowlist setup"
        description="Restrict which origins may embed your widget."
      >
        <p className="text-sm text-muted-foreground">
          By default a new widget is seeded with the registered website&apos;s hostname, so it can
          only be embedded there. To allow more origins, open{' '}
          <strong className="font-medium text-foreground">Widget &rarr; Allowed domains</strong> and
          add bare hostnames.
        </p>
        <Bullets
          items={[
            <>
              <InlineCode>example.com</InlineCode> allows exactly that host (any scheme or port).
            </>,
            <>
              <InlineCode>*.example.com</InlineCode> allows the host and every subdomain.
            </>,
            <>
              <InlineCode>*</InlineCode> allows any origin (not recommended).
            </>,
            <>
              An empty list blocks embeds (the widget stays offline) until you add at least one
              domain.
            </>,
          ]}
        />
        <CodeBlock
          code={ALLOWLIST_EXAMPLE}
          language="text"
          filename="allowed-domains"
          copyLabel="Copy matching examples"
        />
        <Callout variant="warning" title="Server-to-server requests">
          Requests without an <InlineCode>Origin</InlineCode> header (curl, server-to-server) are
          not browser embeds and are not restricted by the allowlist.
        </Callout>
      </DocSection>

      <DocSection
        id="troubleshooting"
        title="Troubleshooting"
        description="Common issues and how to fix them."
      >
        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">Widget does not appear.</strong>{' '}
              Confirm the website is ready and the widget is enabled in the dashboard, then hard
              refresh your page. Config is cached for up to 5 minutes.
            </>,
            <>
              <strong className="font-medium text-foreground">403 Forbidden.</strong> The embedding
              origin is not in the allowlist. Add the site&apos;s hostname under Widget &rarr;
              Allowed domains.
            </>,
            <>
              <strong className="font-medium text-foreground">
                Requests blocked by a Content-Security-Policy.
              </strong>{' '}
              Allow the API origin in your connect-src directive:
            </>,
            <>
              <strong className="font-medium text-foreground">
                &quot;Can&apos;t reach the assistant&quot;.
              </strong>{' '}
              A network failure, mid-stream drop, or connection refused. Check the API endpoint and
              your firewall.
            </>,
            <>
              <strong className="font-medium text-foreground">
                &quot;Message limit reached&quot;.
              </strong>{' '}
              The visitor hit a per-session or rate limit. Try again later.
            </>,
          ]}
        />
        <CodeBlock
          code={CSP_EXAMPLE}
          language="text"
          filename="CSP"
          copyLabel="Copy CSP directive"
        />
        <p className="text-sm text-muted-foreground">
          Ready to install? Follow the{' '}
          <Link
            href="/docs/quickstart"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Quickstart
          </Link>
          .
        </p>
      </DocSection>
    </div>
  );
}
