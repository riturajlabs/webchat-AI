import Link from 'next/link';

import {
  Callout,
  Checklist,
  DocHeader,
  InlineCode,
  RelatedDocs,
  ScreenshotFrame,
  StepCard,
} from '@/components/marketing/docs-ui';
import { CodeBlock } from '@/features/docs/code-block';
import { SCRIPT_TAG } from '@/features/docs/content';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/quickstart',
  title: 'Quickstart Tutorial',
  description:
    'Learn how to build, customize, test, and deploy an AI knowledge assistant in WebChat AI using websites or uploaded documents.',
});

const PROGRESS_STEPS = [
  '01 Account',
  '02 Source',
  '03 Ingest',
  '04 Customize',
  '05 Test',
  '06 Deploy',
  '07 Monitor',
];

export default function QuickstartPage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[{ label: 'Quickstart' }]}
        title="Build your first WebChat AI assistant"
        lede="Go from raw website content or standalone documents to a live, grounded AI assistant on your website in 7 steps."
      />

      {/* Visual Progression Bar */}
      <div className="flex items-center gap-2 overflow-x-auto whitespace-nowrap rounded-xl border border-border/70 bg-muted/40 p-3 pb-3.5 text-xs">
        {PROGRESS_STEPS.map((step, idx) => (
          <span
            key={step}
            className="inline-flex shrink-0 items-center gap-2 font-medium text-muted-foreground"
          >
            <span className="shrink-0 rounded bg-background px-2.5 py-1 font-mono text-[11px] text-foreground shadow-2xs">
              {step}
            </span>
            {idx < PROGRESS_STEPS.length - 1 ? (
              <span className="shrink-0 text-muted-foreground/40">&rarr;</span>
            ) : null}
          </span>
        ))}
      </div>

      <Callout variant="tip" title="What you'll need">
        <ul className="list-disc pl-5 text-sm">
          <li>A WebChat AI account (Free tier includes 1 website and 1,000 monthly messages).</li>
          <li>
            Either a public website URL, or documents in PDF, DOCX, Markdown, or plain text format.
          </li>
          <li>Access to edit the HTML of your website where you wish to embed the assistant.</li>
        </ul>
      </Callout>

      {/* Step 1 */}
      <StepCard
        step="01"
        id="create-account"
        title="Create your account"
        description="Sign up and open your workspace dashboard."
      >
        <p className="text-sm text-muted-foreground">
          Navigate to{' '}
          <Link
            href="/signup"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Sign Up
          </Link>
          . Enter your name, email, and password. Complete email verification if prompted, then log
          in to reach your workspace overview.
        </p>
        <ScreenshotFrame
          src="/docs-assets/screenshots/dashboard.png"
          alt="WebChat AI Workspace Dashboard"
          caption="The WebChat AI dashboard showing websites, knowledge status, and quick links."
        />
      </StepCard>

      {/* Step 2 */}
      <StepCard
        step="02"
        id="choose-source"
        title="Choose your knowledge source mode"
        description="WebChat AI supports websites, upload-only chatbots, and mixed sources."
      >
        <p className="text-sm text-muted-foreground">
          In your dashboard, click the <strong className="text-foreground">Add website</strong>{' '}
          button in the top right corner. Select the source mode that fits your project:
        </p>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-border/70 bg-card p-4">
            <p className="font-semibold text-foreground">Website</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Best when your documentation, product catalog, or FAQs already live on a public site.
            </p>
            <p className="mt-2 text-[11px] font-medium text-blue-600 dark:text-blue-400">
              Requires URL
            </p>
          </div>
          <div className="rounded-lg border border-border/70 bg-card p-4">
            <p className="font-semibold text-foreground">Documents</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Best for creating a chatbot strictly from files (PDF, DOCX, MD, TXT) without a public
              site.
            </p>
            <p className="mt-2 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
              No URL required
            </p>
          </div>
          <div className="rounded-lg border border-border/70 bg-card p-4">
            <p className="font-semibold text-foreground">Mixed</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Combines crawled website pages with proprietary manual file uploads in one corpus.
            </p>
            <p className="mt-2 text-[11px] font-medium text-purple-600 dark:text-purple-400">
              URL + File Uploads
            </p>
          </div>
        </div>

        <ScreenshotFrame
          src="/docs-assets/screenshots/knowledge-source.png"
          alt="Source Selection Modal in WebChat AI"
          caption="Source Mode selection: Website, Documents, or Website + Docs."
        />
      </StepCard>

      {/* Step 3 */}
      <StepCard
        step="03"
        id="add-content"
        title="Add content &amp; wait for processing"
        description="WebChat AI extracts, cleans, chunks, and vectorizes your material."
      >
        <div className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>Depending on your chosen mode:</p>
          <ul className="list-disc pl-5">
            <li>
              <strong className="text-foreground">Website mode:</strong> Enter your URL (e.g.{' '}
              <InlineCode>https://docs.example.com</InlineCode>). WebChat AI automatically crawls
              your pages, stripping out navigation headers, footers, and scripts.
            </li>
            <li>
              <strong className="text-foreground">Documents mode:</strong> Enter an assistant name.
              Open <strong className="text-foreground">Knowledge Base</strong> and upload up to 5
              files per batch (.pdf, .docx, .md, .txt; max 10 MB per file).
            </li>
          </ul>

          <div className="rounded-lg border border-border/70 bg-muted/30 p-3">
            <p className="font-semibold text-xs text-foreground uppercase tracking-wider">
              Document Processing Lifecycle
            </p>
            <div className="mt-2 flex flex-wrap gap-2 text-xs font-mono">
              <span className="rounded bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-400">
                pending
              </span>
              <span>&rarr;</span>
              <span className="rounded bg-blue-500/10 px-2 py-0.5 text-blue-700 dark:text-blue-400">
                processing
              </span>
              <span>&rarr;</span>
              <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-emerald-700 dark:text-emerald-400">
                ready
              </span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Documents are split into 500–800 token chunks with 100-token overlap to preserve
              semantic context. Once the status reaches{' '}
              <strong className="text-emerald-600 dark:text-emerald-400">ready</strong>, your
              knowledge base is searchable.
            </p>
          </div>
        </div>
      </StepCard>

      {/* Step 4 */}
      <StepCard
        step="04"
        id="customize-assistant"
        title="Customize appearance &amp; branding"
        description="Style the widget to match your brand identity."
      >
        <p className="text-sm text-muted-foreground">
          Open <strong className="text-foreground">Widget &rarr; Appearance</strong> in the
          dashboard. You have full control over:
        </p>
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            <strong className="text-foreground">Theme preset:</strong> 11 curated palettes (Classic,
            WhatsApp Classic, iOS Native, Enterprise Slate, Ocean Blue, Midnight Dark, Emerald
            Support, Purple AI, Minimal White, Sunset, Modern Gradient).
          </li>
          <li>
            <strong className="text-foreground">Typography:</strong> 10 font choices (System
            default, Inter, Poppins, Nunito, Roboto, Open Sans, Montserrat, Lato, Playfair Display,
            Space Grotesk).
          </li>
          <li>
            <strong className="text-foreground">Bot identity:</strong> Custom bot name, online
            presence text, avatar image URL, and header logo.
          </li>
          <li>
            <strong className="text-foreground">Suggested questions:</strong> Up to 5 quick-prompt
            chips to guide new visitors.
          </li>
        </ul>
      </StepCard>

      {/* Step 5 */}
      <StepCard
        step="05"
        id="test-assistant"
        title="Test the assistant in staging"
        description="Verify answers, streaming, and citations before public launch."
      >
        <p className="text-sm text-muted-foreground">
          Navigate to <strong className="text-foreground">Widget Test</strong> in the dashboard
          sidebar. This runs the exact live widget SDK inside an isolated test environment.
        </p>
        <ScreenshotFrame
          src="/docs-assets/screenshots/widget-test.png"
          alt="Dashboard Widget Test Page"
          caption="The Widget Test environment lets you verify live streaming responses and citation accuracy."
        />
        <div className="rounded-lg border border-border/70 bg-card p-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Verification Checklist
          </p>
          <Checklist
            items={[
              'Widget launcher button opens and closes smoothly',
              'Welcome message and suggested questions appear on start',
              'Submitting a question streams the response in real time',
              'Citations link back to the exact source documents or URLs',
              'Unanswered questions gracefully trigger the fallback response without hallucinating',
            ]}
          />
        </div>
      </StepCard>

      {/* Step 6 */}
      <StepCard
        step="06"
        id="allowed-domains"
        title="Configure domain allowlist &amp; embed"
        description="Secure your widget against unauthorized embedding."
      >
        <p className="text-sm text-muted-foreground">
          Under <strong className="text-foreground">Widget &rarr; Allowed domains</strong>, enter
          the hostnames permitted to embed your widget (e.g. <InlineCode>example.com</InlineCode> or{' '}
          <InlineCode>*.example.com</InlineCode>). Requests from unlisted origins will receive an
          HTTP 403 Forbidden.
        </p>

        <p className="text-sm text-muted-foreground">
          Copy your embed script from{' '}
          <strong className="text-foreground">Widget &rarr; Embed code</strong> and paste it before
          the closing <InlineCode>&lt;/body&gt;</InlineCode> tag of your website:
        </p>

        <CodeBlock
          code={SCRIPT_TAG}
          language="html"
          filename="index.html"
          copyLabel="Copy script tag"
        />

        <Callout variant="info" title="Config caching notice">
          Public widget configuration is cached server-side in Redis for up to 300 seconds (5
          minutes) with best-effort invalidation upon dashboard updates.
        </Callout>
      </StepCard>

      {/* Step 7 */}
      <StepCard
        step="07"
        id="monitor-usage"
        title="Monitor conversations &amp; analytics"
        description="Inspect visitor interactions and track AI performance."
      >
        <p className="text-sm text-muted-foreground">
          Once your widget is live on your website, visit the dashboard to review operations:
        </p>
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            <strong className="text-foreground">Conversations:</strong> Inspect full message
            transcripts, citations used by the AI, and per-stage latency (embedding, retrieval,
            generation).
          </li>
          <li>
            <strong className="text-foreground">Analytics:</strong> Review conversation volume, peak
            activity hours, top visitor questions, and thumbs up/down satisfaction ratings.
          </li>
          <li>
            <strong className="text-foreground">Usage:</strong> Track message counts and document
            storage against your monthly subscription tier.
          </li>
        </ul>
      </StepCard>

      <RelatedDocs
        links={[
          {
            title: 'Knowledge Sources Guide',
            description: 'Deep dive into website crawls, uploaded documents, and mixed ingestion.',
            href: '/docs/knowledge-sources',
          },
          {
            title: 'File Upload Limits & Processing',
            description: 'Learn supported file formats, character limits, and chunking parameters.',
            href: '/docs/document-upload',
          },
          {
            title: 'Widget Customization',
            description: 'Explore all 11 theme presets, 10 curated fonts, and branding options.',
            href: '/docs/customization',
          },
          {
            title: 'Troubleshooting Guide',
            description: 'Diagnose allowlist 403 errors, CSP directives, and crawler issues.',
            href: '/docs/troubleshooting',
          },
        ]}
      />
    </div>
  );
}
