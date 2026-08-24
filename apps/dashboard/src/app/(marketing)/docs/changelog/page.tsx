import type { Metadata } from 'next';

import { DocsShell, DocSection } from '../_components/docs-shell';

export const metadata: Metadata = {
  title: 'Changelog',
  description: 'Recent changes to the WebChat AI platform and embeddable widget.',
};

const RELEASES = [
  {
    date: 'August 2026',
    title: 'Production hardening & RAG accuracy',
    items: [
      'Hybrid retrieval (vector + keyword with reciprocal-rank fusion) behind a feature flag for better answer grounding.',
      'Reranking and improved context assembly: deduplication, relevance floors and per-answer character budgets.',
      'Widget streaming stability: buffered SSE deltas, disconnect detection and a clearer error taxonomy with retry.',
      'Security hardening: strict embed-origin enforcement, expanded rate limits and audit logging across the API.',
      'Full production audit passed (backend, dashboard, widget SDK).',
    ],
  },
  {
    date: 'July 2026',
    title: 'Widget customization & analytics',
    items: [
      'Widget builder with live preview: theme presets, custom colors, logo, avatar, launcher position.',
      'Suggested questions, welcome message and "Powered by" badge controls.',
      'Analytics: conversation KPIs, daily timeseries, top websites and response performance metrics.',
      'Domain allowlist editor with wildcard support (*.example.com).',
    ],
  },
  {
    date: 'June 2026',
    title: 'Private beta',
    items: [
      'Website registration with crawler → chunker → embedding pipeline into a per-tenant knowledge base.',
      'Streaming RAG chat widget with source citations and hallucination guard (no answer without retrieved context).',
      'Conversations browser, usage metering, API keys and admin console.',
    ],
  },
];

export default function ChangelogPage() {
  return (
    <DocsShell active="/docs/changelog">
      <header className="flex flex-col gap-3">
        <h1 className="font-sans text-3xl font-bold tracking-tight">Changelog</h1>
        <p className="max-w-2xl text-balance text-muted-foreground">
          Notable changes to the platform, dashboard and widget SDK.
        </p>
      </header>

      {RELEASES.map((release) => (
        <DocSection key={release.title} title={release.title} description={release.date}>
          <ul className="list-disc pl-5 text-sm text-muted-foreground">
            {release.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </DocSection>
      ))}
    </DocsShell>
  );
}
