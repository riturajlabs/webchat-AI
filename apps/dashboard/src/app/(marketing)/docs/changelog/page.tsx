import {
  BreadcrumbNav,
  Bullets,
  Callout,
  DocHeader,
  DocSection,
  RelatedDocs,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/changelog',
  title: 'Documentation & integration changelog',
  description:
    'Version history and release notes for WebChat AI documentation, SDK integrations, API surfaces, and widget features.',
});

const RELEASES = [
  {
    version: 'Docs v2.0 — Production Portal Upgrade',
    date: 'September 2026',
    summary:
      'Complete overhaul of the documentation into a 15-page developer and user portal with end-to-end architecture guides, screenshots, interactive diagrams, and curl examples.',
    highlights: [
      'Added Knowledge Sources guide detailing Website, Upload-only Files, and Mixed ingestion modes.',
      'Added File Uploads guide documenting supported formats (.pdf, .docx, .md, .txt), 10 MB/5-file batch caps, 100-page PDF bounds, and document lifecycle statuses.',
      'Added RAG & Grounding guide breaking down dense vector retrieval, lexical IDF scoring, reciprocal rank fusion (RRF), and hallucination prevention guards.',
      'Added Widget Customization reference covering all 11 theme presets (including WhatsApp Classic and iOS Native) and 10 curated Google Fonts with dynamic loader pipeline.',
      'Added Staging & Testing guide detailing the dashboard /widget-test harness and 5-minute cache TTL considerations.',
      'Added Conversations guide covering visitor session isolation, message transcripts, source citations, and latency telemetry.',
      'Added Analytics & Usage guide with KPI metrics, popular query clusters, satisfaction ratings, and plan quota management.',
      'Upgraded REST API reference with copyable curl examples, real JSON request/response payloads, and an exhaustive HTTP error code directory.',
      'Added Security guide covering multi-tenant partitioning, allowed domain origin validation, crawler SSRF defense, and CSP setup.',
      'Added Troubleshooting guide with structured recipes (Symptom, Cause, Check, Fix) for 403, 404, 429, and crawler edge cases.',
      'Enhanced navigation with h2/h3 table-of-contents tracking, instant filterable search, and a mobile drawer.',
    ],
  },
  {
    version: 'Docs v1.0 — Initial Developer Release',
    date: 'August 2026',
    summary:
      'Initial release of developer documentation covering basic embed scripts, core configuration options, and API endpoints.',
    highlights: [
      'Documented script tag embed snippet and npm @webchat/widget integration.',
      'Documented core widget options (primaryColor, botName, welcomeMessage).',
      'Initial REST API route catalog for websites, crawl jobs, and billing.',
    ],
  },
];

export default function ChangelogPage() {
  return (
    <div className="flex flex-col gap-8">
      <BreadcrumbNav
        items={[
          { label: 'Documentation', href: '/docs' },
          { label: 'Reference' },
          { label: 'Changelog' },
        ]}
      />

      <DocHeader
        breadcrumb="Reference / Documentation changelog"
        title="Documentation changelog"
        lede="Version history and notable improvements to WebChat AI documentation, SDK integrations, and developer surfaces."
      />

      {RELEASES.map((release) => (
        <DocSection
          key={release.version}
          id={release.version.toLowerCase().replace(/[^a-z0-9]+/g, '-')}
          title={release.version}
          description={release.date}
        >
          <p className="mb-3 text-sm text-muted-foreground">{release.summary}</p>
          <Bullets items={release.highlights} />
        </DocSection>
      ))}

      <DocSection
        id="standards"
        title="Documentation standards"
        description="Our commitment to technical accuracy and synchronization with production code."
      >
        <p className="text-sm leading-relaxed text-muted-foreground">
          All documentation in this portal is validated directly against the production codebase.
          Option keys, schema limits, API response models, and security behaviors mirror actual
          runtime implementation invariants without marketing inflation or fictional features.
        </p>

        <Callout variant="tip" title="Looking for product release notes?">
          Product release announcements, maintenance schedules, and platform status updates are
          published in the user dashboard and account notifications.
        </Callout>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'Quickstart tutorial',
            href: '/docs/quickstart',
            description: 'Get started from scratch in 7 simple steps.',
          },
          {
            title: 'REST API reference',
            href: '/docs/api',
            description: 'Explore all available HTTP endpoints and payloads.',
          },
          {
            title: 'Widget configuration',
            href: '/docs/configuration',
            description: 'Complete reference of widget settings and theme presets.',
          },
        ]}
      />
    </div>
  );
}
