import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { deriveKnowledgeReadiness, UNKNOWN_READINESS } from '@/features/knowledge/status';
import type { KnowledgeReadiness } from '@/features/knowledge/status';
import { useKnowledgeReadinessForSites } from '@/features/knowledge/hooks';

import { CrawlStatusBanner } from './crawl-status-banner';
import { useWebsites } from '@/features/websites/hooks';
import type { Website } from '@/features/websites/types';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

vi.mock('@/features/knowledge/hooks', () => ({
  useKnowledgeReadinessForSites: vi.fn(),
}));

const mockedUseWebsites = vi.mocked(useWebsites);
const mockedReadiness = vi.mocked(useKnowledgeReadinessForSites);

function mockWebsites(sites: ReturnType<typeof useWebsites>['data']) {
  mockedUseWebsites.mockReturnValue({
    data: sites,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useWebsites>);
}

function mockReadinessFor(sites: Website[], readinessMap: Record<string, KnowledgeReadiness>) {
  mockedReadiness.mockReturnValue(
    sites.map((site) => ({
      site,
      readiness: readinessMap[site.id] ?? UNKNOWN_READINESS,
    })),
  );
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

const BASE: Website = {
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
};

beforeEach(() => {
  mockWebsites([]);
  mockReadinessFor([], {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CrawlStatusBanner', () => {
  it('renders nothing when no websites are crawling or embedding', () => {
    mockWebsites([]);
    mockReadinessFor([], {});
    renderBanner();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders nothing when all websites are truly ready', () => {
    const site = BASE;
    mockWebsites([site]);
    mockReadinessFor([site], {
      [site.id]: deriveKnowledgeReadiness(
        { total: 3, pending: 0, processing: 0, completed: 3, failed: 0, rate_limited: 0 },
        site,
      ),
    });
    renderBanner();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders the embedding banner while the knowledge base is being generated', () => {
    const site: Website = { ...BASE, knowledge_status: 'processing' };
    mockWebsites([site]);
    mockReadinessFor([site], {
      [site.id]: deriveKnowledgeReadiness(
        { total: 3, pending: 0, processing: 1, completed: 2, failed: 0, rate_limited: 0 },
        site,
      ),
    });
    renderBanner();
    expect(screen.getByText('Generating embeddings for Acme…')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Generating embeddings for Acme/ })).toHaveAttribute(
      'href',
      '/websites',
    );
  });

  it('shows the embedding banner even when knowledge_status is prematurely ready but documents are rate_limited', () => {
    const site: Website = { ...BASE, knowledge_status: 'ready' };
    mockWebsites([site]);
    mockReadinessFor([site], {
      [site.id]: deriveKnowledgeReadiness(
        { total: 43, pending: 0, processing: 0, completed: 35, failed: 0, rate_limited: 8 },
        site,
      ),
    });
    renderBanner();
    expect(screen.getByText('Generating embeddings for Acme…')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Crawling/ })).not.toBeInTheDocument();
  });

  it('shows single-site crawl label', () => {
    const site: Website = { ...BASE, status: 'crawling', knowledge_status: 'none' };
    mockWebsites([site]);
    mockReadinessFor([site], {});
    renderBanner();
    expect(screen.getByText('Crawling Acme…')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Crawling Acme/ })).toHaveAttribute(
      'href',
      '/websites',
    );
  });

  it('shows multi-site crawl label', () => {
    const s1: Website = {
      ...BASE,
      id: '1',
      name: 'Acme',
      status: 'crawling',
      knowledge_status: 'none',
    };
    const s2: Website = {
      ...BASE,
      id: '2',
      name: 'Globex',
      url: 'https://globex.com',
      widget_id: 'w2',
      status: 'crawling' as const,
      knowledge_status: 'none' as const,
      knowledge_documents: 0,
      knowledge_chunks: 0,
      last_knowledge_at: null,
    };
    mockWebsites([s1, s2]);
    mockReadinessFor([s1, s2], {});
    renderBanner();
    expect(screen.getByText('Crawling Acme + 1 other site…')).toBeInTheDocument();
  });

  it('shows plural other-sites label for 3+ crawling sites', () => {
    const s1: Website = {
      ...BASE,
      id: '1',
      name: 'Acme',
      status: 'crawling',
      knowledge_status: 'none',
    };
    const s2 = {
      ...BASE,
      id: '2',
      name: 'Globex',
      url: 'https://globex.com',
      widget_id: 'w2',
      status: 'crawling' as const,
      knowledge_status: 'none' as const,
      knowledge_documents: 0,
      knowledge_chunks: 0,
      last_knowledge_at: null,
    };
    const s3 = {
      ...BASE,
      id: '3',
      name: 'Initech',
      url: 'https://initech.com',
      widget_id: 'w3',
      status: 'crawling' as const,
      knowledge_status: 'none' as const,
      knowledge_documents: 0,
      knowledge_chunks: 0,
      last_knowledge_at: null,
    };
    mockWebsites([s1, s2, s3]);
    mockReadinessFor([s1, s2, s3], {});
    renderBanner();
    expect(screen.getByText('Crawling Acme + 2 other sites…')).toBeInTheDocument();
  });

  it('shows the multi-site embedding label', () => {
    const s1: Website = { ...BASE, knowledge_status: 'processing' };
    const s2 = {
      ...BASE,
      id: '2',
      name: 'Globex',
      url: 'https://globex.com',
      widget_id: 'w2',
      knowledge_status: 'processing' as const,
      knowledge_documents: 8,
      knowledge_chunks: 40,
      last_knowledge_at: null,
    };
    mockWebsites([s1, s2]);
    const emb = (site: Website) =>
      deriveKnowledgeReadiness(
        {
          total: 3,
          pending: 0,
          processing: 1,
          completed: 2,
          failed: 0,
          rate_limited: 0,
        },
        site,
      );
    mockReadinessFor([s1, s2], { [s1.id]: emb(s1), [s2.id]: emb(s2) });
    renderBanner();
    expect(screen.getByText('Generating embeddings for Acme + 1 other site…')).toBeInTheDocument();
  });
});
