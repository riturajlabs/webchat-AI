import {
  BreadcrumbNav,
  Callout,
  DocHeader,
  DocSection,
  InlineCode,
  RelatedDocs,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/troubleshooting',
  title: 'Troubleshooting & common error recipes',
  description:
    'Step-by-step diagnostic guide and fixes for common WebChat AI issues: 403 origin errors, CSP violations, crawl failures, upload limits, and quota warnings.',
});

interface DiagnosticIssue {
  id: string;
  title: string;
  symptom: string;
  cause: string;
  check: string;
  fix: string;
}

const ISSUES: DiagnosticIssue[] = [
  {
    id: 'origin-not-allowed',
    title: '403 WIDGET_ORIGIN_NOT_ALLOWED',
    symptom:
      'The widget bubble fails to appear on your website, or browser DevTools console prints a 403 Forbidden error.',
    cause:
      'The embedding website domain is not registered in the assistant’s Allowed Domains list.',
    check:
      'Open browser DevTools -> Network tab. Filter for "config". Check the request origin header and the 403 response payload.',
    fix: 'Navigate to Dashboard -> Assistant Settings -> Allowed Domains. Add your domain (e.g., "example.com" or "*.example.com"). Save changes. Note: Public widget configuration is cached server-side in Redis for up to 300 seconds (5 minutes) with best-effort invalidation upon dashboard updates.',
  },
  {
    id: 'csp-violation',
    title: 'Content Security Policy (CSP) Blocking Widget',
    symptom:
      'Browser console prints: "Refused to load the script... because it violates the following Content Security Policy directive".',
    cause:
      'Your website enforces a Content Security Policy that restricts external script execution or network requests.',
    check:
      'Inspect response headers of your host HTML page for the "Content-Security-Policy" header.',
    fix: "Add the WebChat AI origin to your server’s CSP header:\nscript-src 'self' https://api.webchat.ai;\nconnect-src 'self' https://api.webchat.ai;\nfont-src 'self' https://fonts.gstatic.com;",
  },
  {
    id: 'crawl-zero-pages',
    title: 'Crawler Discovers 0 Pages or Stops Early',
    symptom: 'Crawl job status switches to completed or failed with 0 or 1 pages indexed.',
    cause:
      'The target site robots.txt forbids crawler user-agents, the site is a Single Page App (SPA) without server-rendered HTML links, or the URL resolved to a private/internal IP blocked by SSRF defense.',
    check:
      'Visit https://yourdomain.com/robots.txt in your browser. Inspect whether "Disallow: /" is set. Check if page links require JavaScript execution.',
    fix: 'Adjust robots.txt to allow crawling, provide an XML sitemap URL, or switch the assistant to "Files" / "Mixed" mode and upload exported HTML/PDF documentation directly.',
  },
  {
    id: 'upload-rejected',
    title: 'File Upload Rejected or Document Shows "Failed"',
    symptom:
      'Document upload modal displays a red error banner, or document status shows "failed" in the Knowledge Base table.',
    cause:
      'File exceeds 10 MB, batch has more than 5 files, PDF is encrypted/password-protected, PDF exceeds 100 pages, or file type is unsupported.',
    check:
      'Verify file size and page count on your local machine. Try opening the PDF without entering a password.',
    fix: 'Remove password encryption before uploading, split documents into batches under 10 MB, and click the "Retry" button next to any failed document in the Knowledge Base table.',
  },
  {
    id: 'grounding-fallback',
    title: 'Assistant Answers: "I do not have enough information"',
    symptom:
      'The assistant consistently returns the fallback unknown answer response even for questions related to your product.',
    cause:
      'The RAG hybrid retrieval score fell below the grounding confidence threshold to prevent hallucination.',
    check:
      'Inspect Knowledge Base -> Documents. Verify documents are in "completed" status. Review whether the exact terminology or entity names exist in the ingested text.',
    fix: 'Add an FAQ document (.md or .pdf) containing explicit definitions and concise answers to frequently asked visitor questions, then re-test in the Widget Test harness.',
  },
  {
    id: 'message-quota-exceeded',
    title: '429 MESSAGE_LIMIT_REACHED',
    symptom:
      'Widget displays: "Message limit reached for this month. Please contact the site administrator."',
    cause:
      'Your tenant has reached the monthly message quota allocated to your active subscription plan.',
    check:
      'Check Dashboard -> Analytics or Dashboard -> Billing to review monthly message usage bars.',
    fix: 'Upgrade your subscription tier in the Billing panel. Upgrades take effect immediately and restore widget query capacity.',
  },
];

export default function TroubleshootingDocPage() {
  return (
    <div className="flex flex-col gap-8">
      <BreadcrumbNav
        items={[
          { label: 'Documentation', href: '/docs' },
          { label: 'Developer' },
          { label: 'Troubleshooting' },
        ]}
      />

      <DocHeader
        breadcrumb="Developer / Troubleshooting recipes"
        title="Troubleshooting & diagnostics"
        lede="Quick solutions to verified operational issues, error codes, and configuration conflicts across the crawler, widget, ingestion pipeline, and API."
      />

      <DocSection
        id="common-issues"
        title="Diagnostic recipes"
        description="Structured by symptom, root cause, verification check, and verified resolution."
      >
        <div className="flex flex-col gap-6">
          {ISSUES.map((issue) => (
            <article
              key={issue.id}
              id={issue.id}
              className="flex flex-col gap-3 rounded-lg border border-border/60 bg-card p-5"
            >
              <h3 className="font-sans text-base font-semibold text-foreground">{issue.title}</h3>

              <div className="grid gap-2 text-xs sm:grid-cols-4">
                <span className="font-semibold text-muted-foreground uppercase tracking-wider">
                  Symptom
                </span>
                <p className="sm:col-span-3 text-foreground font-sans">{issue.symptom}</p>
              </div>

              <div className="grid gap-2 text-xs sm:grid-cols-4">
                <span className="font-semibold text-muted-foreground uppercase tracking-wider">
                  Root Cause
                </span>
                <p className="sm:col-span-3 text-muted-foreground font-sans">{issue.cause}</p>
              </div>

              <div className="grid gap-2 text-xs sm:grid-cols-4">
                <span className="font-semibold text-muted-foreground uppercase tracking-wider">
                  Verification
                </span>
                <p className="sm:col-span-3 text-muted-foreground font-sans">{issue.check}</p>
              </div>

              <div className="grid gap-2 text-xs sm:grid-cols-4">
                <span className="font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider">
                  Fix
                </span>
                <div className="sm:col-span-3 text-foreground font-sans whitespace-pre-line leading-relaxed">
                  {issue.fix}
                </div>
              </div>
            </article>
          ))}
        </div>
      </DocSection>

      <DocSection
        id="verifying-in-staging"
        title="Testing in the staging harness"
        description="Verify fixes before redeploying to production environments."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          Whenever you adjust assistant settings, test the change inside the dedicated dashboard
          test harness at <InlineCode>/widget-test</InlineCode>. This isolated dashboard test page
          runs with dashboard origin permissions and hot reloads configuration changes.
        </p>

        <Callout variant="tip" title="Need further assistance?">
          If you continue encountering unexplained issues, check your server container logs for
          uncaught exceptions or open a support inquiry through your account dashboard.
        </Callout>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Security & origin validation',
            href: '/docs/security',
            description: 'Learn how allowed domains and SSRF protections operate.',
          },
          {
            title: 'Testing & verification harness',
            href: '/docs/testing',
            description: 'Use the dashboard Widget Test page for staging verification.',
          },
          {
            title: 'REST API reference',
            href: '/docs/api',
            description: 'Review the full table of HTTP error codes and JSON envelopes.',
          },
        ]}
      />
    </div>
  );
}
