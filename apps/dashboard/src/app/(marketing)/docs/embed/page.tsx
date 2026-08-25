import type { Metadata } from 'next';
import Link from 'next/link';

import { CodeBlock } from '@/features/docs/code-block';
import {
  buildEmbedScript,
  buildInitExample,
  buildMountExample,
  DOCS_WIDGET_ID,
  WIDGET_API_URL,
  WIDGET_SCRIPT_URL,
} from '@/features/widget/embed';
import { Bullets, DocHeader, DocSection, SubHeading } from '@/components/marketing/docs-ui';

export const metadata: Metadata = {
  title: 'Embed',
  description:
    'Embed the WebChat AI widget: hosted script tag, SDK init()/mount() usage, API origin overrides and domain allowlists.',
};

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

export default function EmbedPage() {
  return (
    <div className="flex flex-col gap-6">
      <DocHeader
        title="Embed"
        lede="Two ways to bring the widget into your site — the hosted script or the SDK package — plus domain control and troubleshooting."
      />

      <DocSection
        title="Hosted script (no build step)"
        description="The fastest way to render the assistant."
      >
        <p className="text-sm text-muted-foreground">
          Paste the embed script from your dashboard on{' '}
          <strong className="font-medium text-foreground">Widget &rarr; Embed code</strong>. No
          installation required — the bundle is served from{' '}
          <code className="font-mono text-xs">{WIDGET_SCRIPT_URL}</code>.
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy script tag" />
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
      </DocSection>

      <DocSection
        title="SDK package (framework apps)"
        description="For React, Vue or any bundler-based app."
      >
        <CodeBlock code={INSTALL_COMMAND} language="bash" copyLabel="Copy install command" />
        <p className="text-sm text-muted-foreground">
          Import the SDK and call <code className="font-mono text-xs">init()</code>:
        </p>
        <CodeBlock code={INIT_EXAMPLE} language="ts" copyLabel="Copy init() example" />
        <p className="text-sm text-muted-foreground">
          Or mount into an existing element with <code className="font-mono text-xs">mount()</code>:
        </p>
        <CodeBlock code={MOUNT_EXAMPLE} language="ts" copyLabel="Copy mount() example" />
      </DocSection>

      <DocSection
        title="Domain allowlist setup"
        description="Restrict which origins may embed your widget."
      >
        <div id="domains" className="scroll-mt-24" />
        <p className="text-sm text-muted-foreground">
          By default a new widget is seeded with the registered website&apos;s hostname, so it can
          only be embedded there. To allow more origins, open{' '}
          <strong className="font-medium text-foreground">Widget &rarr; Allowed domains</strong> and
          add bare hostnames.
        </p>
        <Bullets
          items={[
            <>
              <code className="font-mono text-xs">example.com</code> allows exactly that host (any
              scheme or port).
            </>,
            <>
              <code className="font-mono text-xs">*.example.com</code> allows the host and every
              subdomain.
            </>,
            <>
              <code className="font-mono text-xs">*</code> allows any origin (not recommended).
            </>,
            <>
              An empty list blocks embeds (the widget stays offline) until you add at least one
              domain.
            </>,
          ]}
        />
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
      </DocSection>

      <DocSection title="Troubleshooting" description="Common issues and how to fix them.">
        <div id="troubleshooting" className="scroll-mt-24" />
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
        <CodeBlock code={CSP_EXAMPLE} language="text" copyLabel="Copy CSP directive" />
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
