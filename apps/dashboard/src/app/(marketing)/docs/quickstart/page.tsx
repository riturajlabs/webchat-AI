import type { Metadata } from 'next';
import Link from 'next/link';

import { CodeBlock } from '@/features/docs/code-block';
import { buildEmbedScript, DOCS_WIDGET_ID } from '@/features/widget/embed';
import { Bullets, DocHeader, DocSection, SubHeading } from '@/components/marketing/docs-ui';

export const metadata: Metadata = {
  title: 'Quickstart',
  description: 'Install the WebChat AI chat widget on your website in minutes with one script tag.',
};

const SCRIPT_TAG = buildEmbedScript(DOCS_WIDGET_ID);

export default function QuickstartPage() {
  return (
    <div className="flex flex-col gap-6">
      <DocHeader
        title="Quickstart"
        lede="Go from an empty dashboard to a live chatbot on your website. You only need a registered website and access to your site's HTML."
      />

      <DocSection
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
      </DocSection>

      <DocSection
        title="2. Copy your embed script"
        description="Each website has its own widget id, shown in Widget → Embed code."
      >
        <p className="text-sm text-muted-foreground">
          Replace <code className="font-mono text-xs">{DOCS_WIDGET_ID}</code> below with your real
          widget id:
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy embed script" />
      </DocSection>

      <DocSection
        title="3. Paste it into your site"
        description="Add the script before the closing </body> tag of every page that should show the assistant."
      >
        <p className="text-sm text-muted-foreground">
          The <code className="font-mono text-xs">defer</code> attribute keeps the script from
          blocking page render; the launcher appears once the bundle has run.
        </p>
      </DocSection>

      <DocSection
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
            Embed → Domain allowlist
          </Link>
          .
        </p>
      </DocSection>

      <DocSection title="Next steps" description="Where to go from here.">
        <SubHeading>Related</SubHeading>
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
