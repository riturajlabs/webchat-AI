import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CrawlStatusBanner } from './crawl-status-banner';
import { useWebsites } from '@/features/websites/hooks';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

const mockedUseWebsites = vi.mocked(useWebsites);

function mockWebsites(sites: ReturnType<typeof useWebsites>['data']) {
  mockedUseWebsites.mockReturnValue({
    data: sites,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useWebsites>);
}

function renderBanner() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CrawlStatusBanner />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockWebsites([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CrawlStatusBanner', () => {
  it('renders nothing when no websites are crawling', () => {
    mockWebsites([]);
    renderBanner();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders nothing when all websites are ready', () => {
    mockWebsites([
      {
        id: '1',
        name: 'Acme',
        url: 'https://acme.com',
        status: 'ready',
        tenant_id: 't1',
        pages_indexed: 5,
        last_crawled_at: '2026-08-25T00:00:00Z',
        checksum: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
        widget_id: 'w1',
        knowledge_status: 'ready',
        knowledge_documents: 3,
        knowledge_chunks: 20,
        last_knowledge_at: '2026-08-25T00:00:00Z',
      },
    ]);
    renderBanner();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows single-site crawl label', () => {
    mockWebsites([
      {
        id: '1',
        name: 'Acme',
        url: 'https://acme.com',
        status: 'crawling',
        tenant_id: 't1',
        pages_indexed: 0,
        last_crawled_at: null,
        checksum: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
        widget_id: 'w1',
        knowledge_status: 'none',
        knowledge_documents: 0,
        knowledge_chunks: 0,
        last_knowledge_at: null,
      },
    ]);
    renderBanner();
    expect(screen.getByText('Crawling Acme…')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Crawling Acme/ })).toHaveAttribute(
      'href',
      '/websites',
    );
  });

  it('shows multi-site crawl label', () => {
    mockWebsites([
      {
        id: '1',
        name: 'Acme',
        url: 'https://acme.com',
        status: 'crawling',
        tenant_id: 't1',
        pages_indexed: 0,
        last_crawled_at: null,
        checksum: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
        widget_id: 'w1',
        knowledge_status: 'none',
        knowledge_documents: 0,
        knowledge_chunks: 0,
        last_knowledge_at: null,
      },
      {
        id: '2',
        name: 'Globex',
        url: 'https://globex.com',
        status: 'crawling',
        tenant_id: 't1',
        pages_indexed: 0,
        last_crawled_at: null,
        checksum: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
        widget_id: 'w2',
        knowledge_status: 'none',
        knowledge_documents: 0,
        knowledge_chunks: 0,
        last_knowledge_at: null,
      },
    ]);
    renderBanner();
    expect(screen.getByText('Crawling Acme + 1 other site…')).toBeInTheDocument();
  });

  it('shows plural other-sites label for 3+ crawling sites', () => {
    const base = {
      tenant_id: 't1',
      pages_indexed: 0,
      last_crawled_at: null,
      checksum: null,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-25T00:00:00Z',
      knowledge_status: 'none' as const,
      knowledge_documents: 0,
      knowledge_chunks: 0,
      last_knowledge_at: null,
    };
    mockWebsites([
      {
        id: '1',
        name: 'Acme',
        url: 'https://acme.com',
        status: 'crawling',
        widget_id: 'w1',
        ...base,
      },
      {
        id: '2',
        name: 'Globex',
        url: 'https://globex.com',
        status: 'crawling',
        widget_id: 'w2',
        ...base,
      },
      {
        id: '3',
        name: 'Initech',
        url: 'https://initech.com',
        status: 'crawling',
        widget_id: 'w3',
        ...base,
      },
    ]);
    renderBanner();
    expect(screen.getByText('Crawling Acme + 2 other sites…')).toBeInTheDocument();
  });
});
