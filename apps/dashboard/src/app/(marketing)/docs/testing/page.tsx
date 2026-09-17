import {
  Callout,
  Checklist,
  DocHeader,
  DocSection,
  InlineCode,
  RelatedDocs,
  ScreenshotFrame,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/testing',
  title: 'Widget Testing & Staging',
  description:
    'Test and verify your AI assistant in staging using the dashboard Widget Test environment before embedding on your production site.',
});

export default function TestingPage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[{ label: 'Widget', href: '/docs/embed' }, { label: 'Testing' }]}
        title="Widget Testing &amp; Staging Verification"
        lede="Verify your assistant's knowledge, streaming responses, citations, and theme appearance in an isolated staging environment."
      />

      <ScreenshotFrame
        src="/docs-assets/screenshots/widget-test.png"
        alt="WebChat AI Dashboard Widget Test Page"
        caption="The Widget Test page runs the real WebChat AI widget SDK in an isolated dashboard test page."
      />

      {/* The Dashboard Widget Test Page */}
      <DocSection
        id="widget-test-page"
        title="The dashboard Widget Test environment"
        description="What it is and how it exercises your real runtime."
      >
        <div className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>
            Rather than requiring you to embed code on a live website to test changes, WebChat AI
            includes a dedicated test harness at{' '}
            <strong className="text-foreground">Widget Test</strong> in your dashboard sidebar.
          </p>
          <ul className="list-disc pl-5">
            <li>
              <strong className="text-foreground">Real SDK Runtime:</strong> Renders inside an
              isolated iframe running the exact production{' '}
              <InlineCode>webchat-widget.js</InlineCode> bundle.
            </li>
            <li>
              <strong className="text-foreground">Live Configuration:</strong> Pulls your latest
              saved theme, bot name, suggested questions, and branding options in real time.
            </li>
            <li>
              <strong className="text-foreground">Active RAG Index:</strong> Queries your real
              knowledge base and tests answer grounding and citation linking.
            </li>
          </ul>
        </div>
      </DocSection>

      {/* Testing Checklist */}
      <DocSection
        id="test-checklist"
        title="Staging verification checklist"
        description="Run through these checks before publishing the widget to visitors."
      >
        <Checklist
          items={[
            'Launcher open/close: Click the launcher button to verify smooth opening, closing, and viewport positioning.',
            'Suggested questions: Confirm your configured prompt chips appear and trigger queries on click.',
            'Streaming tokens: Check that AI answers stream smoothly without choppy pauses or buffer stutter.',
            'Source citations: Click citations beneath answers to verify they link to the correct document or crawled URL.',
            'Grounding & fallback: Ask an out-of-scope question and confirm the bot gracefully returns the fallback without fabricating information.',
            'Theme & contrast: Verify your text colors, header gradients, and button accents maintain good readability.',
            'Mobile responsiveness: Test on mobile viewports to ensure the full-screen chat drawer functions properly.',
          ]}
        />
      </DocSection>

      {/* Localhost and Staging Testing */}
      <DocSection
        id="localhost-testing"
        title="Testing on localhost or staging servers"
        description="How to test in local web development environments."
      >
        <div className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>
            If you are embedding the widget in a local web development environment (e.g. Next.js,
            Vite, or WordPress running on localhost), you must add your local development origin to
            the allowlist:
          </p>
          <div className="rounded-lg border border-border/70 bg-muted/30 p-3 font-mono text-xs text-foreground">
            localhost
          </div>
          <p className="text-xs">
            Add <InlineCode>localhost</InlineCode> under{' '}
            <strong className="text-foreground">Widget &rarr; Allowed domains</strong>. WebChat AI
            matches hostnames regardless of the port (e.g. <InlineCode>localhost:3000</InlineCode>{' '}
            and <InlineCode>localhost:8000</InlineCode> both match).
          </p>
          <Callout variant="warning" title="Remove localhost in production">
            Before deploying to public production, remember to remove development origins from the
            allowlist to keep embedding strictly confined to your live domains.
          </Callout>
        </div>
      </DocSection>

      {/* Config Caching Notice */}
      <DocSection
        id="config-caching"
        title="Configuration caching (5-minute TTL)"
        description="Understanding server-side cache duration during testing."
      >
        <p className="text-sm text-muted-foreground">
          Widget public configuration is cached server-side in Redis for up to 300 seconds (5
          minutes) with best-effort invalidation upon dashboard updates.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          When you update settings in the dashboard, the cache key is purged immediately. If Redis
          is temporarily unreachable, the service falls back directly to the database, ensuring
          configuration updates apply reliably.
        </p>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Customization Reference',
            description: 'Learn how to customize themes, typography, and bot branding.',
            href: '/docs/customization',
          },
          {
            title: 'Embed Guide',
            description: 'Deploy the tested widget to your production website.',
            href: '/docs/embed',
          },
          {
            title: 'Troubleshooting Guide',
            description: 'Solve origin rejections, CSP directives, and streaming drops.',
            href: '/docs/troubleshooting',
          },
        ]}
      />
    </div>
  );
}
