import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WebsiteCard } from './website-card';
import type { Website } from './types';

const SITE: Website = {
  id: 'site-1',
  tenant_id: 'tenant-1',
  name: 'Acme Inc',
  url: 'https://acme.example.com',
  status: 'ready',
  pages_indexed: 12,
  last_crawled_at: '2026-08-01T00:00:00Z',
  checksum: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  widget_id: 'widget-1',
  knowledge_status: 'ready',
  knowledge_documents: 3,
  knowledge_chunks: 42,
  last_knowledge_at: null,
};

function renderCard(website: Website = SITE) {
  return render(
    <div className="w-64">
      <WebsiteCard
        website={website}
        crawlJob={null}
        crawlProgress={null}
        sseConnected={false}
        crawlPending={false}
        onCrawl={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />
    </div>,
  );
}

describe('WebsiteCard responsive behavior', () => {
  it('wraps the action buttons instead of forcing the card wider than its container', () => {
    renderCard();
    const crawlButton = screen.getByRole('button', { name: 'Crawl now' });
    // The actions row wraps so the three nowrap buttons stack on narrow cards
    // instead of making the card's min-content wider than the viewport.
    expect(crawlButton.parentElement).toHaveClass('flex-wrap');
    expect(crawlButton.parentElement).toHaveClass('gap-2');
  });

  it('truncates long website URLs rather than blowing out the card width', () => {
    const url = 'https://example.com/very/long/path?with=query&params=that&never=end';
    renderCard({ ...SITE, url });
    const link = screen.getByRole('link', { name: /https:\/\/example\.com/ });
    // Inline-level (`inline-flex`) overflow-hidden boxes are sized to their
    // max-content and overflow their line, so the link must be a block-level
    // flex box with min-w-0 to be allowed to shrink below the URL width.
    expect(link).toHaveClass('flex');
    expect(link).toHaveClass('min-w-0');
    // The URL label is a real flex item with overflow-hidden that actually
    // truncates once the link is constrained by its container.
    const urlLabel = screen.getByText(url);
    expect(urlLabel).toHaveClass('truncate');
    expect(urlLabel).toHaveClass('min-w-0');
    // The URL sits inside a min-w-0 flex column so truncation can actually
    // shrink instead of widening the card.
    expect(link.closest('.min-w-0')).not.toBeNull();
  });
});
