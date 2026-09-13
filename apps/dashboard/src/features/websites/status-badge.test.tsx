import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

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

describe('WebsiteStatusBadge', () => {
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
