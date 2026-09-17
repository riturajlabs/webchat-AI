import { FileText, Globe, Layers } from 'lucide-react';

import {
  DocHeader,
  DocSection,
  RelatedDocs,
  ScreenshotFrame,
} from '@/components/marketing/docs-ui';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs/knowledge-sources',
  title: 'Knowledge Sources',
  description:
    'Explore the three knowledge source modes in WebChat AI: public website crawling, upload-only document chatbots, and mixed sources.',
});

const MODES = [
  {
    mode: 'Website',
    id: 'website',
    tag: 'Automated Crawl',
    icon: Globe,
    description:
      'WebChat AI crawls a public domain or subdomain, following links and indexing pages automatically.',
    urlRequired: true,
    fileUploads: 'Optional (via mixed conversion)',
    bestFor: 'Public documentation portals, company marketing sites, e-commerce stores, and blogs.',
    behavior:
      'The crawler discovers pages, strips navigation and boilerplate, and chunks text into 500–800 token passages.',
  },
  {
    mode: 'Documents',
    id: 'documents',
    tag: 'Upload-Only Chatbot',
    icon: FileText,
    description:
      'Create an AI assistant powered strictly by uploaded proprietary files (.pdf, .docx, .md, .txt) without needing a website URL.',
    urlRequired: false,
    fileUploads: 'Primary source (up to 5 files / 10 MB per batch)',
    bestFor:
      'Internal knowledge bases, customer support runbooks, policy manuals, and technical specifications.',
    behavior:
      'Files are uploaded via multipart form, text is extracted, and passages are vectorized directly into tenant storage.',
  },
  {
    mode: 'Mixed',
    id: 'mixed',
    tag: 'Unified Corpus',
    icon: Layers,
    description:
      'Combines content crawled from a public website with additional manual document uploads in a single unified knowledge base.',
    urlRequired: true,
    fileUploads: 'Supported alongside website crawls',
    bestFor:
      'Companies whose public website has base knowledge, but who need to supplement it with offline PDFs or guides.',
    behavior:
      'Citations link to public URLs for crawled pages and show file download badges for uploaded documents.',
  },
];

export default function KnowledgeSourcesPage() {
  return (
    <div className="flex flex-col gap-10">
      <DocHeader
        breadcrumbs={[
          { label: 'Knowledge', href: '/docs/knowledge-sources' },
          { label: 'Knowledge Sources' },
        ]}
        title="Knowledge Sources &amp; Ingestion Modes"
        lede="WebChat AI allows you to train assistants from live websites, uploaded documents, or a combination of both."
      />

      <ScreenshotFrame
        src="/docs-assets/screenshots/knowledge-source.png"
        alt="WebChat AI Source Mode Selector"
        caption="Select between Website, Documents (Upload-Only), and Website + Docs when creating an assistant."
        priority
      />

      {/* Comparison Table */}
      <DocSection
        id="mode-comparison"
        title="Source modes comparison"
        description="Detailed feature breakdown across the three ingestion modes."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Knowledge source modes comparison</caption>
            <thead>
              <tr className="border-b border-border/80 text-muted-foreground">
                <th scope="col" className="py-2.5 pr-4 font-semibold">
                  Source Mode
                </th>
                <th scope="col" className="py-2.5 pr-4 font-semibold">
                  Website URL
                </th>
                <th scope="col" className="py-2.5 pr-4 font-semibold">
                  File Uploads
                </th>
                <th scope="col" className="py-2.5 font-semibold">
                  Best For
                </th>
              </tr>
            </thead>
            <tbody>
              {MODES.map((m) => (
                <tr key={m.mode} className="border-b border-border/50 last:border-0 align-top">
                  <td className="py-3 pr-4 font-semibold text-foreground">
                    <div className="flex items-center gap-2">
                      <m.icon
                        className="size-4 text-blue-600 dark:text-blue-400"
                        aria-hidden="true"
                      />
                      <span>{m.mode}</span>
                    </div>
                  </td>
                  <td className="py-3 pr-4 text-xs font-mono text-muted-foreground">
                    {m.urlRequired ? (
                      <span className="rounded bg-blue-500/10 px-2 py-0.5 text-blue-600 dark:text-blue-400">
                        Required
                      </span>
                    ) : (
                      <span className="rounded bg-muted px-2 py-0.5 text-muted-foreground">
                        Not required
                      </span>
                    )}
                  </td>
                  <td className="py-3 pr-4 text-xs text-muted-foreground">{m.fileUploads}</td>
                  <td className="py-3 text-xs text-muted-foreground">{m.bestFor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DocSection>

      {/* Deep Dives into each mode */}
      {MODES.map((m) => (
        <DocSection key={m.id} id={m.id} title={`${m.mode} Mode (${m.tag})`}>
          <p className="text-sm text-muted-foreground">{m.description}</p>
          <div className="rounded-lg border border-border/70 bg-muted/20 p-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              How it works
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{m.behavior}</p>
          </div>
          <div className="text-xs text-muted-foreground">
            <strong className="text-foreground">Recommended when:</strong> {m.bestFor}
          </div>
        </DocSection>
      ))}

      <DocSection
        id="ssrf-and-security"
        title="Crawler security &amp; SSRF guard"
        description="How WebChat AI ensures secure website ingestion."
      >
        <p className="text-sm text-muted-foreground">
          When crawling websites, WebChat AI enforces strict network-level security protections:
        </p>
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          <li>
            <strong className="text-foreground">SSRF Protection:</strong> Blocks navigation to
            loopback (127.0.0.1, localhost), private subnet ranges (10.0.0.0/8, 172.16.0.0/12,
            192.168.0.0/16), and cloud metadata endpoints (169.254.169.254).
          </li>
          <li>
            <strong className="text-foreground">DNS Rebinding Mitigation:</strong> Hostnames are
            re-resolved fresh before every single page fetch and redirect hop.
          </li>
          <li>
            <strong className="text-foreground">Port Filtering:</strong> Non-HTTP ports (SSH,
            database, SMTP) are rejected.
          </li>
        </ul>
      </DocSection>

      <RelatedDocs
        links={[
          {
            title: 'File Upload Formats & Limits',
            description: 'Learn supported file types, character bounds, and processing statuses.',
            href: '/docs/document-upload',
          },
          {
            title: 'RAG & Retrieval Pipeline',
            description:
              'Understand how chunks are embedded, searched, and cited in chat responses.',
            href: '/docs/rag-pipeline',
          },
          {
            title: 'Quickstart Guide',
            description: 'Follow the 7-step guide to connect content and launch the assistant.',
            href: '/docs/quickstart',
          },
        ]}
      />
    </div>
  );
}
