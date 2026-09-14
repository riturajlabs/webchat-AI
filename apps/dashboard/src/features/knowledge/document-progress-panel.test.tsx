import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { DocumentProgressPanel } from './document-progress-panel';
import type { KnowledgeDocumentsResponse } from './types';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { api } from '@/lib/api';
import { toast } from 'sonner';

const mockedGet = vi.mocked(api.get);

const DOCS = [
  {
    id: 'doc-1',
    website_id: 'site-1',
    url: 'https://example.com/',
    title: 'Example',
    status: 'processing',
    failure_reason: null,
    retry_count: 0,
    last_attempt_at: '2026-09-14T00:00:00Z',
    chunks: 0,
  },
  {
    id: 'doc-2',
    website_id: 'site-1',
    url: 'https://example.com/pricing',
    title: 'Pricing',
    status: 'failed',
    failure_reason: '429 Too Many Requests',
    retry_count: 2,
    last_attempt_at: '2026-09-14T00:00:00Z',
    chunks: 0,
  },
  {
    id: 'doc-3',
    website_id: 'site-1',
    url: 'https://example.com/terms',
    title: 'Terms',
    status: 'completed',
    failure_reason: null,
    retry_count: 0,
    last_attempt_at: '2026-09-14T00:00:00Z',
    chunks: 4,
  },
] satisfies KnowledgeDocumentsResponse['documents'];

const RESPONSE: KnowledgeDocumentsResponse = {
  website_id: 'site-1',
  summary: {
    total: 3,
    completed: 1,
    processing: 1,
    pending: 0,
    failed: 1,
    rate_limited: 0,
  },
  documents: DOCS,
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <DocumentProgressPanel websiteId="site-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DocumentProgressPanel', () => {
  it('loads the per-document status from the documents endpoint', async () => {
    mockedGet.mockResolvedValue(RESPONSE);
    renderPanel();
    expect(await screen.findByText('Generating embeddings…')).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith('/api/knowledge/websites/site-1/documents');
  });

  it('renders truthful counts with no synthetic percentage', async () => {
    mockedGet.mockResolvedValue(RESPONSE);
    renderPanel();
    const panel = await screen.findByTestId('document-progress-panel');
    const counts = within(panel).getAllByRole('definition');
    expect(counts.map((node) => node.textContent)).toEqual(['3', '1', '1', '0', '1', '0']);
    expect(within(panel).getByText('Total')).toBeInTheDocument();
    expect(within(panel).getByText('Retry scheduled')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('calls out the page that is currently being processed', async () => {
    mockedGet.mockResolvedValue(RESPONSE);
    renderPanel();
    const callout = await screen.findByRole('status');
    expect(callout).toHaveTextContent('Current processing');
    expect(callout).toHaveTextContent('Example');
  });

  it('lists every document with its state badge, including rate_limited', async () => {
    mockedGet.mockResolvedValue({
      ...RESPONSE,
      summary: { total: 4, completed: 3, processing: 0, pending: 0, failed: 0, rate_limited: 1 },
      documents: [
        ...DOCS,
        {
          id: 'doc-4',
          website_id: 'site-1',
          url: 'https://example.com/faq',
          title: 'FAQ',
          status: 'rate_limited',
          failure_reason: null,
          retry_count: 1,
          last_attempt_at: '2026-09-14T00:00:00Z',
          chunks: 0,
        },
      ],
    });
    renderPanel();
    expect(await screen.findByText('FAQ')).toBeInTheDocument();
    expect(screen.getAllByText('Retry scheduled').length).toBeGreaterThanOrEqual(1);
  });

  it('surfaces failure_reason for failed pages', async () => {
    mockedGet.mockResolvedValue(RESPONSE);
    renderPanel();
    expect(await screen.findByText('429 Too Many Requests')).toBeInTheDocument();
  });

  it('retries a failed document and refreshes the cache', async () => {
    mockedGet.mockResolvedValue(RESPONSE);
    vi.mocked(api.post).mockResolvedValue({
      document_id: 'doc-2',
      website_id: 'site-1',
      status: 'pending',
    });
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /retry/i }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/knowledge/documents/doc-2/retry'),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Document re-queued for embedding.'),
    );
  });

  it('does not attempt to render counts until documents have loaded', () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByLabelText('Loading document status')).toBeInTheDocument();
  });
});
