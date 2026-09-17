import {
  Bullets,
  DocHeader,
  DocSection,
  InlineCode,
  RelatedDocs,
} from '@/components/marketing/docs-ui';
import { CodeBlock } from '@/features/docs/code-block';
import { Tabs } from '@/features/docs/docs-client';
import {
  ALLOWLIST_EXAMPLE,
  CSP_EXAMPLE,
  INSTALL_COMMAND,
  MOUNT_EXAMPLE,
  SCRIPT_TAG,
  SCRIPT_TAG_WITH_API,
  WIDGET_SCRIPT_URL,
} from '@/features/docs/content';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/embed',
  title: 'Widget Embed Guide',
  description:
    'Integrate the WebChat AI widget using the zero-build hosted script or the @webchat/widget SDK package. Includes React, Next.js, CSP, and origin security.',
});

const REACT_EXAMPLE = `'use client';

import { useEffect } from 'react';
import { init } from '@webchat/widget';

export function ChatAssistant() {
  useEffect(() => {
    const dispose = init({
      widgetId: 'YOUR_WIDGET_ID',
    });
    return () => dispose();
  }, []);

  return null;
}`;

const NEXTJS_SCRIPT_EXAMPLE = `import Script from 'next/script';

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        {children}
        <Script
          src="${WIDGET_SCRIPT_URL}"
          data-widget-id="YOUR_WIDGET_ID"
          strategy="lazyOnload"
        />
      </body>
    </html>
  );
}`;

export default function EmbedPage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[{ label: 'Widget', href: '/docs/embed' }, { label: 'Embed Guide' }]}
        title="Widget Embed &amp; Integration Guide"
        lede="Deploy your assistant to any website using the zero-build hosted script tag or the @webchat/widget npm package."
      />

      {/* Option 1: Hosted Script */}
      <DocSection
        id="hosted-script"
        title="1. Hosted script tag (Zero build step)"
        description="Recommended for standard HTML sites, WordPress, Webflow, Shopify, and static websites."
      >
        <p className="text-sm text-muted-foreground">
          Copy your embed script from the dashboard under{' '}
          <strong className="text-foreground">Widget &rarr; Embed code</strong> and paste it
          directly before the closing <InlineCode>&lt;/body&gt;</InlineCode> tag:
        </p>

        <CodeBlock
          code={SCRIPT_TAG}
          language="html"
          filename="index.html"
          copyLabel="Copy hosted script"
        />

        <div className="mt-4">
          <h3 id="api-origin" className="scroll-mt-24 text-sm font-semibold text-foreground">
            Custom API Origin Override
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            If you reverse-proxy the widget API through your own domain to avoid third-party
            requests, specify <InlineCode>data-api-base-url</InlineCode>:
          </p>
          <div className="mt-2">
            <CodeBlock
              code={SCRIPT_TAG_WITH_API}
              language="html"
              filename="index.html"
              copyLabel="Copy script with API override"
            />
          </div>
        </div>
      </DocSection>

      {/* Option 2: SDK Package */}
      <DocSection
        id="sdk-package"
        title="2. SDK Package (Modern frontend frameworks)"
        description="For React, Next.js, Vue, or Vite single-page applications."
      >
        <p className="text-sm text-muted-foreground">
          Install the lightweight package into your project dependencies:
        </p>

        <CodeBlock
          code={INSTALL_COMMAND}
          language="bash"
          filename="terminal"
          copyLabel="Copy npm command"
        />

        <div className="mt-4">
          <Tabs
            defaultValue="react"
            tabs={[
              {
                label: 'React / SPA',
                value: 'react',
                content: (
                  <div className="flex flex-col gap-2">
                    <p className="text-xs text-muted-foreground">
                      Initialize the widget on component mount and clean up on unmount:
                    </p>
                    <CodeBlock
                      code={REACT_EXAMPLE}
                      language="tsx"
                      filename="ChatAssistant.tsx"
                      copyLabel="Copy React example"
                    />
                  </div>
                ),
              },
              {
                label: 'Next.js App Router',
                value: 'nextjs',
                content: (
                  <div className="flex flex-col gap-2">
                    <p className="text-xs text-muted-foreground">
                      Load the hosted script using Next.js Script component in root layout:
                    </p>
                    <CodeBlock
                      code={NEXTJS_SCRIPT_EXAMPLE}
                      language="tsx"
                      filename="app/layout.tsx"
                      copyLabel="Copy Next.js example"
                    />
                  </div>
                ),
              },
              {
                label: 'Container mount()',
                value: 'mount',
                content: (
                  <div className="flex flex-col gap-2">
                    <p className="text-xs text-muted-foreground">
                      Mount into a custom DOM element instead of document.body:
                    </p>
                    <CodeBlock
                      code={MOUNT_EXAMPLE}
                      language="ts"
                      filename="custom-mount.ts"
                      copyLabel="Copy mount example"
                    />
                  </div>
                ),
              },
            ]}
          />
        </div>
      </DocSection>

      {/* Domain Allowlists */}
      <DocSection
        id="allowed-domains"
        title="Domain allowlists &amp; origin validation"
        description="Restrict which websites are permitted to render your assistant."
      >
        <div className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>
            WebChat AI validates the browser&apos;s <InlineCode>Origin</InlineCode> header on every
            public widget request. If a site embedding your widget is not listed in your allowed
            domains, the backend returns{' '}
            <strong className="text-foreground">HTTP 403 Forbidden</strong> and the widget remains
            inactive.
          </p>

          <CodeBlock
            code={ALLOWLIST_EXAMPLE}
            language="text"
            filename="domain-matching-rules"
            copyLabel="Copy matching rules"
          />

          <Bullets
            items={[
              <>
                <strong className="text-foreground">Exact host:</strong>{' '}
                <InlineCode>example.com</InlineCode> allows that specific hostname on any port or
                scheme (http/https).
              </>,
              <>
                <strong className="text-foreground">Wildcard subdomain:</strong>{' '}
                <InlineCode>*.example.com</InlineCode> allows any subdomain like{' '}
                <InlineCode>docs.example.com</InlineCode> or{' '}
                <InlineCode>app.example.com</InlineCode>.
              </>,
              <>
                <strong className="text-foreground">Open wildcard:</strong>{' '}
                <InlineCode>*</InlineCode> allows any website to embed the widget (not recommended
                for production).
              </>,
              <>
                <strong className="text-foreground">Empty allowlist:</strong> Upload-only chatbots
                start with an empty allowlist for security; add your production hostname before
                going live.
              </>,
            ]}
          />
        </div>
      </DocSection>

      {/* Content Security Policy */}
      <DocSection
        id="csp-configuration"
        title="Content Security Policy (CSP)"
        description="Configuring host security headers to allow widget traffic."
      >
        <p className="text-sm text-muted-foreground">
          If your website serves a strict Content Security Policy, add the WebChat AI API origin to
          your <InlineCode>connect-src</InlineCode> directive:
        </p>

        <CodeBlock
          code={CSP_EXAMPLE}
          language="text"
          filename="CSP Header"
          copyLabel="Copy CSP directive"
        />
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Staging & Testing Guide',
            description: 'Test your widget in the dashboard Widget Test page before public deploy.',
            href: '/docs/testing',
          },
          {
            title: 'Customization Reference',
            description: 'Learn how to customize themes, fonts, and bot branding.',
            href: '/docs/customization',
          },
          {
            title: 'Troubleshooting Guide',
            description: 'Solve 403 origin errors, CSP blocks, and script loading issues.',
            href: '/docs/troubleshooting',
          },
        ]}
      />
    </div>
  );
}
