import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useCrawlJob, useDeleteWebsite, useStartCrawl, useWebsites } from './hooks';
import { WebsiteList } from './website-list';
import type { CrawlJob, Website } from './types';

vi.mock('./hooks', () => ({
  useWebsites: vi.fn(),
  useDeleteWebsite: vi.fn(),
  useStartCrawl: vi.fn(),
  useCrawlJob: vi.fn(),
  websitesKeys: { all: ['websites'] as const },
}));

vi.mock('./add-website-dialog', () => ({
  AddWebsiteDialog: (props: { open: boolean }) => (
    <div data-testid="add-website-dialog" data-open={String(props.open)} />
  ),
}));

const mockedUseWebsites = vi.mocked(useWebsites);
const mockedUseDeleteWebsite = vi.mocked(useDeleteWebsite);
const mockedUseStartCrawl = vi.mocked(useStartCrawl);
const mockedUseCrawlJob = vi.mocked(useCrawlJob);

const SITE: Website = {
  id: 'site-1',
  tenant_id: 'tenant-1',
  name: 'Acme Inc',
  url: 'https://acme.example.com',
  status: 'ready',
  pages_indexed: 42,
  last_crawled_at: null,
  checksum: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  widget_id: 'widget-1',
};

const COMPLETED_JOB: CrawlJob = {
  id: 'job-1',
  website_id: 'site-1',
  status: 'completed',
  pages_total: 2,
  pages_completed: 2,
  errors: [],
  started_at: '2026-08-01T00:00:00Z',
  completed_at: '2026-08-01T00:00:05Z',
  error_message: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:05Z',
};

type WebsitesState = Partial<ReturnType<typeof useWebsites>>;

function mockWebsites(state: WebsitesState) {
  mockedUseWebsites.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useWebsites>);
}

function mockCrawlJob(job: CrawlJob | null) {
  mockedUseCrawlJob.mockReturnValue({
    data: job,
    isPending: false,
  } as unknown as ReturnType<typeof useCrawlJob>);
}

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <WebsiteList />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockWebsites({ data: [SITE] });
  mockedUseDeleteWebsite.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useDeleteWebsite>);
  mockedUseStartCrawl.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({ crawl_job_id: 'job-1' }),
  } as unknown as ReturnType<typeof useStartCrawl>);
  mockCrawlJob(null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WebsiteList', () => {
  it('shows a loading state while pending', () => {
    mockWebsites({ isPending: true, data: undefined });
    renderList();
    expect(screen.getByRole('status')).toHaveTextContent('Loading websites…');
  });

  it('shows an error state with a retry action', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockWebsites({ isError: true, error: new Error('Failed to load websites.'), refetch });
    renderList();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load websites.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('shows an empty state when there are no websites', () => {
    mockWebsites({ data: [] });
    renderList();
    expect(screen.getByText('No websites yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add your first website' })).toBeInTheDocument();
  });

  it('renders the websites when loaded', () => {
    renderList();
    expect(screen.getByText('Acme Inc')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /acme.example.com/ })).toBeInTheDocument();
    expect(screen.getByText('ready')).toBeInTheDocument();
  });

  it('opens the dialog when clicking Add website', () => {
    renderList();
    expect(screen.getByTestId('add-website-dialog')).toHaveAttribute('data-open', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Add website' }));
    expect(screen.getByTestId('add-website-dialog')).toHaveAttribute('data-open', 'true');
  });

  it('deletes a website after confirmation', () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteWebsite.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useDeleteWebsite
    >);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(window.confirm).toHaveBeenCalledWith('Delete "Acme Inc"? This also removes its widget.');
    expect(mutateAsync).toHaveBeenCalledWith('site-1');
  });

  it('does not delete when confirmation is declined', () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteWebsite.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useDeleteWebsite
    >);
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it('starts a crawl and tracks the active job', () => {
    const mutateAsync = vi.fn().mockResolvedValue({ crawl_job_id: 'job-1', status: 'pending' });
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));

    expect(mutateAsync).toHaveBeenCalledWith('site-1');
  });

  it('disables the crawl button while starting', () => {
    const mutateAsync = vi.fn().mockImplementation(() => new Promise(() => undefined));
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));

    const starting = screen.getByRole('button', { name: 'Starting…' });
    expect(starting).toBeDisabled();
  });

  it('shows a crawl failure message and allows retrying', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('A crawl is already in progress.'));
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('A crawl is already in progress.');
    expect(screen.getByRole('button', { name: 'Crawl now' })).toBeEnabled();
  });

  it('renders live crawl progress for the matching website', () => {
    const running: CrawlJob = {
      ...COMPLETED_JOB,
      status: 'running',
      pages_total: 5,
      pages_completed: 2,
    };
    mockCrawlJob(running);

    renderList();
    expect(screen.getByRole('status')).toHaveTextContent('Crawling… 2/5 pages');
  });

  it('shows the failed alert from the crawl job with a retry action', () => {
    const failed: CrawlJob = {
      ...COMPLETED_JOB,
      status: 'failed',
      error_message: 'Browser crashed',
      errors: [],
    };
    mockCrawlJob(failed);

    renderList();
    expect(screen.getByRole('alert')).toHaveTextContent('Browser crashed');
    expect(screen.getByRole('button', { name: 'Retry crawl' })).toBeInTheDocument();
  });
});
