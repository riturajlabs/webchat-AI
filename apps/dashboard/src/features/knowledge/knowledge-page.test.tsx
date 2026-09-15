import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { deriveKnowledgeReadiness, UNKNOWN_READINESS } from './status';

import { KnowledgePage } from './knowledge-page';
import {
  useKnowledgeDocuments,
  useKnowledgeReadinessForSites,
  useRetryDocument,
  useUploadDocuments,
  useDeleteDocument,
} from './hooks';
import type { KnowledgeDocumentsResponse } from './types';
import type { Website } from '@/features/websites/types';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

vi.mock('./hooks', () => ({
  useKnowledgeDocuments: vi.fn(),
  useKnowledgeReadinessForSites: vi.fn(),
  useRetryDocument: vi.fn(),
  useUploadDocuments: vi.fn(),
  useDeleteDocument: vi.fn(),
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
const mockedUseKnowledgeReadinessForSites = vi.mocked(useKnowledgeReadinessForSites);
const mockedUseRetryDocument = vi.mocked(useRetryDocument);
const mockedUseUploadDocuments = vi.mocked(useUploadDocuments);
const mockedUseDeleteDocument = vi.mocked(useDeleteDocument);

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
  summary: { total: 3, pending: 0, processing: 0, completed: 2, failed: 1, rate_limited: 0 },
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
  summary: { total: 3, pending: 7, processing: 1, completed: 1, failed: 1, rate_limited: 0 },
  documents: [
    ...READY_RESPONSE.documents,
    {
      id: 'doc-processing-1',
      website_id: 'site-1',
      url: 'https://acme.example.com/reports',
      title: 'Reports',
      status: 'processing',
      failure_reason: null,
      retry_count: 0,
      last_attempt_at: '2026-08-02T00:02:00Z',
      chunks: 0,
    },
  ],
};

const EMBEDDING_SUMMARY = {
  total: 43,
  pending: 7,
  processing: 1,
  completed: 35,
  failed: 0,
  rate_limited: 0,
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

function mockReadinessForSites(
  sites: Website[],
  overrides: Record<string, ReturnType<typeof deriveKnowledgeReadiness>> = {},
) {
  mockedUseKnowledgeReadinessForSites.mockReturnValue(
    sites.map((site) => {
      const readiness =
        overrides[site.id] ??
        (site.knowledge_status === 'ready'
          ? deriveKnowledgeReadiness(
              { total: 3, pending: 0, processing: 0, completed: 3, failed: 0, rate_limited: 0 },
              site,
            )
          : site.knowledge_status === 'processing'
            ? deriveKnowledgeReadiness(EMBEDDING_SUMMARY, site)
            : UNKNOWN_READINESS);
      return { site, readiness };
    }),
  );
}

function mockRetry() {
  mockedUseRetryDocument.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({ document_id: 'doc-fail-1', status: 'processing' }),
  } as unknown as ReturnType<typeof useRetryDocument>);
}

function mockUpload() {
  mockedUseUploadDocuments.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({
      website_id: 'site-1',
      total_uploaded: 1,
      documents: [
        {
          id: 'doc-upload-1',
          file_name: 'test.pdf',
          file_size_bytes: 1024,
          mime_type: 'application/pdf',
          status: 'pending',
        },
      ],
    }),
    isPending: false,
  } as unknown as ReturnType<typeof useUploadDocuments>);
}

function mockDelete() {
  mockedUseDeleteDocument.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({
      document_id: 'doc-ready-1',
      status: 'deleted',
    }),
    isPending: false,
  } as unknown as ReturnType<typeof useDeleteDocument>);
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
  mockReadinessForSites([SITE]);
  mockDocuments(READY_RESPONSE);
  mockRetry();
  mockUpload();
  mockDelete();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('KnowledgePage', () => {
  it('shows a loading state while websites are pending', () => {
    mockWebsites({ isPending: true, data: undefined });
    mockReadinessForSites([]);
    renderPage();
    expect(screen.getByRole('heading', { name: 'Knowledge Base' })).toBeInTheDocument();
  });

  it('shows an error state with a retry action', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockWebsites({ isError: true, error: new Error('Failed to load.'), refetch });
    mockReadinessForSites([]);
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

  it('shows the knowledge base setup guide when there are no websites', () => {
    mockWebsites({ data: [] });
    mockReadinessForSites([]);
    renderPage();
    expect(screen.getByText('Build your knowledge base')).toBeInTheDocument();
    expect(screen.getByText('Add your website URL')).toBeInTheDocument();
    expect(screen.getByText('Crawl to extract content')).toBeInTheDocument();
    expect(screen.getByText('AI learns from your content')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add your first website' })).toBeInTheDocument();
  });

  it('does not count a site as ready while its documents are still embedding', () => {
    const premature: Website = { ...SITE, knowledge_status: 'ready' };
    mockWebsites({ data: [premature] });
    // The persisted flag says 'ready' but the /documents summary proves the
    // pipeline is still active — the header stat must follow the documents.
    mockReadinessForSites([premature], {
      [premature.id]: deriveKnowledgeReadiness(EMBEDDING_SUMMARY, premature),
    });
    renderPage();
    // Header stat reflects the per-document truth, not the premature flag.
    const statCard = screen.getByText('Websites ready').closest('.rounded-lg') as HTMLElement;
    expect(within(statCard).getByText('0')).toBeInTheDocument();
    // The row badge never renders a green "ready".
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
    expect(screen.getAllByText('Generating embeddings…').length).toBeGreaterThanOrEqual(1);
  });

  it('counts a site as ready only when its documents confirm the pipeline drained', () => {
    const ready: Website = { ...SITE, knowledge_status: 'ready' };
    mockWebsites({ data: [ready] });
    mockReadinessForSites([ready]);
    renderPage();
    const statCard = screen.getByText('Websites ready').closest('.rounded-lg') as HTMLElement;
    expect(within(statCard).getByText('1')).toBeInTheDocument();
    expect(screen.getAllByText('ready').length).toBeGreaterThanOrEqual(1);
  });

  it('reveals the per-document status breakdown by default and allows collapsing', () => {
    renderPage();
    const toggleButton = screen.getByRole('button', { name: /Hide documents/ });
    expect(toggleButton).toHaveAttribute('aria-expanded', 'true');
    expect(toggleButton).toHaveAttribute('aria-controls', 'website-docs-site-1');

    const detail = screen.getByTestId('document-progress-panel');
    expect(within(detail).getByText('Total')).toBeInTheDocument();
    expect(within(detail).getAllByText('Completed').length).toBeGreaterThanOrEqual(1);
    expect(within(detail).getAllByText('Failed').length).toBeGreaterThanOrEqual(1);
    // Summary numbers from the response.
    expect(within(detail).getByText('3')).toBeInTheDocument();
    expect(within(detail).getByText('2')).toBeInTheDocument();
    expect(within(detail).getAllByText('1').length).toBeGreaterThanOrEqual(1);
    expect(within(detail).getByRole('link', { name: /Pricing/ })).toBeInTheDocument();
    expect(within(detail).getByText('EmbeddingError: provider timeout')).toBeInTheDocument();

    // Collapsing hides the panel and updates the button label
    fireEvent.click(toggleButton);
    expect(screen.queryByTestId('document-progress-panel')).not.toBeInTheDocument();
    const showButton = screen.getByRole('button', { name: /Show documents/ });
    expect(showButton).toHaveAttribute('aria-expanded', 'false');

    // Expanding shows it again
    fireEvent.click(showButton);
    expect(screen.getByTestId('document-progress-panel')).toBeInTheDocument();
  });

  it('names the page currently being processed instead of inventing a percentage', () => {
    mockDocuments(PROCESSING_RESPONSE);
    renderPage();

    expect(screen.getByRole('status')).toHaveTextContent('Current processing');
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('does not show a progress bar once processing completes', () => {
    renderPage();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('retries a failed document from the list', async () => {
    const mutateAsync = vi
      .fn()
      .mockResolvedValue({ document_id: 'doc-fail-1', status: 'processing' });
    mockedUseRetryDocument.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useRetryDocument
    >);

    renderPage();
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
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    const { toast } = await import('sonner');
    expect(toast.error).toHaveBeenCalledWith('Retry failed.');
  });

  it('opens the upload files dialog when clicking Upload files button', () => {
    renderPage();
    const uploadButton = screen.getByRole('button', { name: /Upload files/i });
    expect(uploadButton).toBeInTheDocument();
    fireEvent.click(uploadButton);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Upload Knowledge Files/i })).toBeInTheDocument();
  });
});
