import Link from 'next/link';

import { CodeBlock } from '@/features/docs/code-block';
import { buildEmbedScript, DOCS_WIDGET_ID } from '@/features/widget/embed';
import {
  Bullets,
  Callout,
  DocHeader,
  DocSection,
  InlineCode,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/quickstart',
  title: 'Quickstart',
  description:
    'Install the WebChat AI chat widget on your website in minutes with one script tag. Register a site, copy the embed, paste it and verify.',
});

const SCRIPT_TAG = buildEmbedScript(DOCS_WIDGET_ID);

export default function QuickstartPage() {
  return (
    <div className="flex flex-col gap-8">
      <DocHeader
        breadcrumb="Getting started / Quickstart"
        title="Quickstart"
        lede="Go from an empty dashboard to a live chatbot on your website. You only need a registered website and access to your site's HTML."
      />

      <Callout variant="tip" title="What you'll need">
        <ul className="list-disc pl-5">
          <li>An account with at least one registered website.</li>
          <li>Write access to the HTML where the assistant should appear.</li>
        </ul>
      </Callout>

      <DocSection
        id="connect-your-website"
        title="1. Connect your website"
        description="Register the site you want the assistant to serve."
      >
        <Bullets
          items={[
            'Sign up and open Dashboard → Websites → Add website.',
            'Enter your site URL — WebChat AI crawls your pages and builds the knowledge base.',
            'Wait for the crawl to finish; the site status turns ready when indexing completes.',
          ]}
        />
        <Callout variant="info" title="Indexing">
          The first crawl can take a minute or two depending on the number of pages. You can check
          progress under Dashboard → Websites → the site&apos;s status.
        </Callout>
      </DocSection>

      <DocSection
        id="copy-your-embed"
        title="2. Copy your embed script"
        description="Each website has its own widget id, shown in Widget → Embed code."
      >
        <p className="text-sm text-muted-foreground">
          Replace <InlineCode>{DOCS_WIDGET_ID}</InlineCode> below with your real widget id:
        </p>
        <CodeBlock
          code={SCRIPT_TAG}
          language="html"
          filename="index.html"
          copyLabel="Copy embed script"
        />
      </DocSection>

      <DocSection
        id="paste-into-your-site"
        title="3. Paste it into your site"
        description="Add the script before the closing </body> tag of every page that should show the assistant."
      >
        <p className="text-sm text-muted-foreground">
          The <InlineCode>defer</InlineCode> attribute keeps the script from blocking page render;
          the launcher appears once the bundle has run.
        </p>
      </DocSection>

      <DocSection
        id="check-the-allowlist"
        title="4. Check the domain allowlist"
        description="The widget only renders on origins you allow."
      >
        <p className="text-sm text-muted-foreground">
          A new widget is seeded with your registered hostname automatically, so the first install
          works out of the box. If you serve the site from other origins, add them under{' '}
          <Link
            href="/docs/embed#domains"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed &rarr; Domain allowlist
          </Link>
          .
        </p>
      </DocSection>

      <DocSection
        id="verify"
        title="5. Verify it works"
        description="Open the page and confirm the launcher renders."
      >
        <Bullets
          items={[
            'Hard-refresh the page and look for the launcher in the corner you configured.',
            'Open the chat and ask a question — the assistant should answer from your pages.',
            'If the widget does not appear, check the troubleshooting section in Embed.',
          ]}
        />
        <Callout variant="important" title="Config caching">
          Widget configuration is cached for up to 5 minutes. After you save changes, refresh the
          page a couple of times before judging the result.
        </Callout>
      </DocSection>

      <DocSection id="next-steps" title="Next steps" description="Where to go from here.">
        <Bullets
          items={[
            <>
              Customize appearance and behavior in{' '}
              <Link
                href="/docs/configuration"
                className="font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Configuration
              </Link>
              .
            </>,
            <>
              Framework apps can mount programmatically — see{' '}
              <Link
                href="/docs/embed"
                className="font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Embed
              </Link>
              .
            </>,
            <>
              Build custom integrations against{' '}
              <Link
                href="/docs/api"
                className="font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                API
              </Link>
              .
            </>,
          ]}
        />
      </DocSection>
    </div>
  );
}
