import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { KnowledgePage } from './knowledge-page';
import { useKnowledgeDocuments, useRetryDocument } from './hooks';
import type { KnowledgeDocumentsResponse } from './types';
import type { Website } from '@/features/websites/types';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

vi.mock('./hooks', () => ({
  useKnowledgeDocuments: vi.fn(),
  useRetryDocument: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn() })),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockedUseWebsites = vi.mocked((await import('@/features/websites/hooks')).useWebsites);
const mockedUseKnowledgeDocuments = vi.mocked(useKnowledgeDocuments);
const mockedUseRetryDocument = vi.mocked(useRetryDocument);

const SITE: Website = {
  id: 'site-1',
  tenant_id: 'tenant-1',
  name: 'Acme Inc',
  url: 'https://acme.example.com',
  status: 'ready',
  pages_indexed: 3,
  last_crawled_at: '2026-08-02T00:00:00Z',
  checksum: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-02T00:00:00Z',
  widget_id: 'widget-1',
  knowledge_status: 'processing',
  knowledge_chunks: 27,
  knowledge_documents: 3,
  last_knowledge_at: '2026-08-02T00:00:00Z',
};

const READY_RESPONSE: KnowledgeDocumentsResponse = {
  website_id: 'site-1',
  summary: { total: 3, pending: 0, processing: 0, completed: 2, failed: 1 },
  documents: [
    {
      id: 'doc-ready-1',
      website_id: 'site-1',
      url: 'https://acme.example.com/about',
      title: 'About',
      status: 'completed',
      failure_reason: null,
      retry_count: 0,
      last_attempt_at: '2026-08-02T00:00:00Z',
      chunks: 4,
    },
    {
      id: 'doc-fail-1',
      website_id: 'site-1',
      url: 'https://acme.example.com/pricing',
      title: 'Pricing',
      status: 'failed',
      failure_reason: 'EmbeddingError: provider timeout',
      retry_count: 3,
      last_attempt_at: '2026-08-02T00:01:00Z',
      chunks: 0,
    },
  ],
};

const PROCESSING_RESPONSE: KnowledgeDocumentsResponse = {
  website_id: 'site-1',
  summary: { total: 3, pending: 0, processing: 1, completed: 1, failed: 1 },
  documents: [...READY_RESPONSE.documents],
};

function mockWebsites(state: Partial<ReturnType<typeof mockedUseWebsites>> = {}) {
  mockedUseWebsites.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof mockedUseWebsites>);
}

function mockDocuments(
  response: KnowledgeDocumentsResponse | undefined,
  state: Partial<ReturnType<typeof useKnowledgeDocuments>> = {},
) {
  mockedUseKnowledgeDocuments.mockReturnValue({
    data: response,
    isPending: false,
    isError: false,
    error: null,
    ...state,
  } as unknown as ReturnType<typeof useKnowledgeDocuments>);
}

function mockRetry() {
  mockedUseRetryDocument.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({ document_id: 'doc-fail-1', status: 'processing' }),
  } as unknown as ReturnType<typeof useRetryDocument>);
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <KnowledgePage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockWebsites({ data: [SITE] });
  mockDocuments(READY_RESPONSE);
  mockRetry();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('KnowledgePage', () => {
  it('shows a loading state while websites are pending', () => {
    mockWebsites({ isPending: true, data: undefined });
    renderPage();
    expect(screen.getByRole('heading', { name: 'Knowledge Base' })).toBeInTheDocument();
  });

  it('shows an error state with a retry action', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockWebsites({ isError: true, error: new Error('Failed to load.'), refetch });
    renderPage();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('shows the aggregate stats', () => {
    renderPage();
    expect(screen.getByText('Total chunks')).toBeInTheDocument();
    expect(screen.getByText('27')).toBeInTheDocument();
    expect(screen.getByText('Documents embedded')).toBeInTheDocument();
    expect(screen.getByText('Websites ready')).toBeInTheDocument();
  });

  it('shows an empty state when there are no websites', () => {
    mockWebsites({ data: [] });
    renderPage();
    expect(screen.getByText('No knowledge yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Go to websites' })).toBeInTheDocument();
  });

  it('reveals the per-document status breakdown when opening a website', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }));

    const detail = within(screen.getByTestId('website-knowledge-detail'));
    expect(detail.getByText('Total')).toBeInTheDocument();
    expect(detail.getByText('Processed')).toBeInTheDocument();
    expect(detail.getByText('Failed')).toBeInTheDocument();
    // Summary numbers from the response.
    expect(detail.getByText('3')).toBeInTheDocument();
    expect(detail.getByText('2')).toBeInTheDocument();
    expect(detail.getByText('1')).toBeInTheDocument();
    expect(detail.getByRole('link', { name: /acme.example.com\/pricing/ })).toBeInTheDocument();
    expect(detail.getByText('EmbeddingError: provider timeout')).toBeInTheDocument();
  });

  it('shows embedding progress while documents are processing', () => {
    mockDocuments(PROCESSING_RESPONSE);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }));

    expect(screen.getByRole('status', { name: 'Embedding progress' })).toHaveTextContent(
      'Embedding… 2/3 documents processed',
    );
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '67');
  });

  it('does not show a progress bar once processing completes', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }));
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('retries a failed document from the list', async () => {
    const mutateAsync = vi
      .fn()
      .mockResolvedValue({ document_id: 'doc-fail-1', status: 'processing' });
    mockedUseRetryDocument.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useRetryDocument
    >);

    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith('doc-fail-1'));
    const { toast } = await import('sonner');
    expect(toast.success).toHaveBeenCalledWith('Document re-queued for embedding.');
  });

  it('shows an error toast when the retry fails', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('Retry failed.'));
    mockedUseRetryDocument.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useRetryDocument
    >);

    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Documents' }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const { toast } = await import('sonner');
    expect(toast.error).toHaveBeenCalledWith('Retry failed.');
  });
});
