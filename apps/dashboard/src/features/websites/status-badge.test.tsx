import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { deriveKnowledgeReadiness, UNKNOWN_READINESS } from '@/features/knowledge/status';
import type { KnowledgeDocumentSummary } from '@/features/knowledge/types';

import { StatusBadge, WebsiteStatusBadge } from './status-badge';
import type { Website } from './types';

const SITE: Website = {
  id: 'site-1',
  tenant_id: 'tenant-1',
  name: 'Acme Inc',
  url: 'https://acme.example.com',
  status: 'ready',
  pages_indexed: 0,
  last_crawled_at: null,
  checksum: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  widget_id: 'widget-1',
  knowledge_status: 'ready',
  knowledge_documents: 0,
  knowledge_chunks: 0,
  last_knowledge_at: null,
};

const summary = (overrides: Partial<KnowledgeDocumentSummary>): KnowledgeDocumentSummary => ({
  total: 0,
  pending: 0,
  processing: 0,
  completed: 0,
  failed: 0,
  rate_limited: 0,
  ...overrides,
});

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="ready" />);
    expect(screen.getByText('ready')).toBeInTheDocument();
  });

  it.each([
    ['pending', 'bg-muted'],
    ['crawling', 'bg-blue-100'],
    ['processing', 'bg-amber-100'],
    ['ready', 'bg-green-100'],
    ['failed', 'bg-red-100'],
  ] as const)('applies the %s style', (status, className) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(status)).toHaveClass(className);
  });
});

describe('WebsiteStatusBadge — legacy path (no per-document readiness)', () => {
  it('shows ready only when the crawl AND the knowledge base are both ready', () => {
    render(<WebsiteStatusBadge website={SITE} />);
    expect(screen.getByText('ready')).toBeInTheDocument();
    expect(screen.queryByText(/generating embeddings/i)).not.toBeInTheDocument();
  });

  it('never shows ready while the knowledge base is still being embedded', () => {
    render(<WebsiteStatusBadge website={{ ...SITE, knowledge_status: 'processing' }} />);
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
    expect(screen.getByText('Generating embeddings…')).toBeInTheDocument();
  });

  it('shows failed when the crawl failed', () => {
    render(<WebsiteStatusBadge website={{ ...SITE, status: 'failed' }} />);
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.queryByText(/generating embeddings/i)).not.toBeInTheDocument();
  });

  it('falls back to the raw crawl state when neither settled nor embedding', () => {
    render(
      <WebsiteStatusBadge website={{ ...SITE, status: 'crawling', knowledge_status: 'none' }} />,
    );
    expect(screen.getByText('crawling')).toBeInTheDocument();
    expect(screen.queryByText(/generating embeddings/i)).not.toBeInTheDocument();
  });
});

describe('WebsiteStatusBadge — derived readiness path', () => {
  it('shows ready only when the per-document summary confirms every document is done', () => {
    const readiness = deriveKnowledgeReadiness(summary({ total: 43, completed: 43 }), SITE);
    render(<WebsiteStatusBadge website={SITE} readiness={readiness} />);
    expect(screen.getByText('ready')).toBeInTheDocument();
  });

  it('never shows ready while documents are processing even with a premature backend knowledge_status', () => {
    const readiness = deriveKnowledgeReadiness(
      summary({ total: 43, completed: 35, processing: 1, pending: 7 }),
      SITE,
    );
    render(
      <WebsiteStatusBadge website={{ ...SITE, knowledge_status: 'ready' }} readiness={readiness} />,
    );
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
    expect(screen.getByText('Generating embeddings…')).toBeInTheDocument();
  });

  it('never shows ready while documents are rate_limited', () => {
    const readiness = deriveKnowledgeReadiness(
      summary({ total: 43, completed: 35, rate_limited: 8 }),
      SITE,
    );
    render(<WebsiteStatusBadge website={SITE} readiness={readiness} />);
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
    expect(screen.getByText('Generating embeddings…')).toBeInTheDocument();
  });

  it('shows Checking… while the documents have not been observed, even if knowledge_status is ready', () => {
    render(<WebsiteStatusBadge website={SITE} readiness={UNKNOWN_READINESS} />);
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
    expect(screen.getByText('Checking…')).toBeInTheDocument();
  });

  it('shows failed when every document drained to failed', () => {
    const readiness = deriveKnowledgeReadiness(summary({ total: 43, failed: 43 }), {
      ...SITE,
      knowledge_status: 'failed',
    });
    render(
      <WebsiteStatusBadge
        website={{ ...SITE, knowledge_status: 'failed' }}
        readiness={readiness}
      />,
    );
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
  });

  it('falls back to the crawl status when known, settled, but the crawl is not done', () => {
    const readiness = deriveKnowledgeReadiness(summary({ total: 0, completed: 0 }), {
      ...SITE,
      status: 'processing',
      knowledge_status: 'none',
    });
    render(
      <WebsiteStatusBadge website={{ ...SITE, status: 'processing' }} readiness={readiness} />,
    );
    expect(screen.getByText('processing')).toBeInTheDocument();
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
  });
});
