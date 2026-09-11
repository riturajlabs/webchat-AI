import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDeleteWebsite, useStartCrawl, useWebsites } from './hooks';
import { activeCrawlStore } from './active-crawl-store';
import { useCrawlActivity } from './crawl-activity-context';
import { WebsiteList } from './website-list';
import { DEFAULT_WEBSITE_IMAGE } from './constants';
import type { CrawlActivity } from './crawl-activity-context';
import type { CrawlJob, Website } from './types';

vi.mock('./hooks', () => ({
  useWebsites: vi.fn(),
  useDeleteWebsite: vi.fn(),
  useStartCrawl: vi.fn(),
  websitesKeys: { all: ['websites'] as const },
  TERMINAL_CRAWL_STATUSES: new Set(['completed', 'failed']),
}));

vi.mock('./active-crawl-store', () => ({
  activeCrawlStore: { set: vi.fn(), remove: vi.fn() },
}));

vi.mock('./crawl-activity-context', () => ({
  useCrawlActivity: vi.fn(),
}));

vi.mock('./add-website-dialog', () => ({
  AddWebsiteDialog: (props: { open: boolean }) => (
    <div data-testid="add-website-dialog" data-open={String(props.open)} />
  ),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockedUseWebsites = vi.mocked(useWebsites);
const mockedUseDeleteWebsite = vi.mocked(useDeleteWebsite);
const mockedUseStartCrawl = vi.mocked(useStartCrawl);
const mockedUseCrawlActivity = vi.mocked(useCrawlActivity);
const mockedStoreSet = vi.mocked(activeCrawlStore.set);

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
  knowledge_status: 'processing',
  knowledge_documents: 3,
  knowledge_chunks: 27,
  last_knowledge_at: '2026-08-02T00:00:00Z',
};

const SITE2: Website = {
  ...SITE,
  id: 'site-2',
  name: 'Other Site',
  url: 'https://other.example.com',
  widget_id: 'widget-2',
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

function mockActivity(activity: Partial<CrawlActivity>) {
  mockedUseCrawlActivity.mockReturnValue({
    crawlJob: null,
    crawlProgress: null,
    sseConnected: false,
    ...activity,
  });
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
  sessionStorage.clear();
  mockWebsites({ data: [SITE] });
  mockedUseDeleteWebsite.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useDeleteWebsite>);
  mockedUseStartCrawl.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({ crawl_job_id: 'job-1' }),
  } as unknown as ReturnType<typeof useStartCrawl>);
  mockActivity({});
  mockedStoreSet.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('WebsiteList', () => {
  it('shows a loading state while pending', () => {
    mockWebsites({ isPending: true, data: undefined });
    renderList();
    expect(screen.getByRole('status', { name: 'Loading websites' })).toBeInTheDocument();
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

  it('renders a website preview image and falls back to the default when it is broken', () => {
    mockWebsites({
      data: [{ ...SITE, preview_image: 'https://cdn.example/acme.png' }],
    });
    const { container } = renderList();

    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('src', 'https://cdn.example/acme.png');

    fireEvent.error(img as HTMLImageElement);
    const fallback = container.querySelector('img');
    expect(fallback).not.toBeNull();
    expect(fallback).toHaveAttribute('src', DEFAULT_WEBSITE_IMAGE);
    expect(screen.getByText('Acme Inc')).toBeInTheDocument();
  });

  it('renders the default artwork when a website has no preview image', () => {
    const { container } = renderList();

    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('src', DEFAULT_WEBSITE_IMAGE);
  });

  it('shows the knowledge base statistics in the advanced details section', () => {
    renderList();
    fireEvent.click(screen.getByRole('button', { name: /Advanced details/ }));
    const dts = screen.getAllByText('Knowledge status');
    expect(dts.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Chunks created')).toBeInTheDocument();
    expect(screen.getByText('27')).toBeInTheDocument();
    expect(screen.getByText('Documents embedded')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('opens the dialog when clicking Add website', () => {
    renderList();
    expect(screen.getByTestId('add-website-dialog')).toHaveAttribute('data-open', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Add website' }));
    expect(screen.getByTestId('add-website-dialog')).toHaveAttribute('data-open', 'true');
  });

  it('deletes a website after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteWebsite.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useDeleteWebsite
    >);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    await act(async () => {
      await mutateAsync;
    });
    await vi.waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith('site-1');
    });
  });

  it('does not delete when confirmation is declined', () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockedUseDeleteWebsite.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useDeleteWebsite
    >);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it('starts a crawl and tracks the active job with the app-wide store', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ crawl_job_id: 'job-1', status: 'pending' });
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith('site-1');
      expect(mockedStoreSet).toHaveBeenCalledWith('site-1', 'job-1');
    });
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

  it('clears the error banner when a crawl completes successfully', async () => {
    const completed: CrawlJob = { ...COMPLETED_JOB };

    // First call fails, second call succeeds
    const mutateAsync = vi
      .fn()
      .mockRejectedValueOnce(new Error('Rate limited'))
      .mockResolvedValue({ crawl_job_id: 'job-1' });
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();

    // Trigger a failed crawl to show the error banner
    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Rate limited');

    // The app-wide monitor now reports the job as completed; starting again
    // clears the banner (and the terminal state keeps it cleared).
    mockActivity({ crawlJob: completed });

    // Now start a new crawl that succeeds
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    });

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  it('does not hide a new error when a previous error was cleared', async () => {
    const mutateAsync = vi
      .fn()
      .mockRejectedValueOnce(new Error('First error'))
      .mockRejectedValueOnce(new Error('Second error'));
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();

    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('First error');

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('Second error');
    expect(screen.queryByText('First error')).not.toBeInTheDocument();
  });

  it('renders live crawl progress for the matching website while a job is active', () => {
    const running: CrawlJob = {
      ...COMPLETED_JOB,
      status: 'running',
      pages_total: 5,
      pages_completed: 2,
    };
    mockActivity({ crawlJob: running });

    renderList();

    expect(screen.getByRole('status')).toHaveTextContent(/Crawling…/);
    expect(screen.getByRole('status')).toHaveTextContent(/2 \/ 5 pages/);
  });

  it('shows a failed crawl job with a retry action', () => {
    const failed: CrawlJob = {
      ...COMPLETED_JOB,
      status: 'failed',
      error_message: 'Browser crashed',
      errors: [],
    };
    mockActivity({ crawlJob: failed });

    renderList();

    const retry = screen.getByRole('button', { name: 'Retry crawl' });
    expect(retry).toBeEnabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Crawl failed');
  });

  it('shows the rate-limited crawl state instead of a generic failure', () => {
    const rateLimited: CrawlJob = {
      ...COMPLETED_JOB,
      status: 'failed',
      pages_completed: 1,
      error_message: 'Rate limited by the target website',
      errors: [
        {
          url: 'https://acme.example.com',
          message: 'HTTP 429',
          classification: 'target_rate_limited',
          status_code: 429,
        },
      ],
    };
    mockActivity({ crawlJob: rateLimited });

    renderList();

    expect(screen.getByRole('alert')).toHaveTextContent('Crawl rate-limited');
  });

  it('does not render progress for websites without an active job', () => {
    renderList();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  Multi-job activity tests                                           */
/* ------------------------------------------------------------------ */

describe('WebsiteList — multi-job activity', () => {
  const RUNNING_JOB_1: CrawlJob = {
    ...COMPLETED_JOB,
    id: 'job-1',
    website_id: 'site-1',
    status: 'running',
    pages_total: 10,
    pages_completed: 3,
  };

  const RUNNING_JOB_2: CrawlJob = {
    ...COMPLETED_JOB,
    id: 'job-2',
    website_id: 'site-2',
    status: 'running',
    pages_total: 8,
    pages_completed: 1,
  };

  beforeEach(() => {
    mockWebsites({ data: [SITE, SITE2] });
    mockedUseCrawlActivity.mockImplementation(
      (_websiteId) =>
        ({
          crawlJob: null,
          crawlProgress: null,
          sseConnected: false,
        }) as CrawlActivity,
    );
  });

  it('renders progress for multiple simultaneous crawls independently', async () => {
    mockedUseCrawlActivity.mockImplementation(
      (websiteId) =>
        ({
          crawlJob: websiteId === 'site-1' ? RUNNING_JOB_1 : RUNNING_JOB_2,
          crawlProgress: null,
          sseConnected: false,
        }) as CrawlActivity,
    );

    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce({ crawl_job_id: 'job-1' })
      .mockResolvedValueOnce({ crawl_job_id: 'job-2' });
    mockedUseStartCrawl.mockReturnValue({
      mutateAsync,
    } as unknown as ReturnType<typeof useStartCrawl>);

    renderList();

    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: 'Crawl now' })[0]);
    });
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: 'Crawl now' })[1]);
    });

    const statuses = () => screen.getAllByRole('status');
    expect(statuses().some((el) => el.textContent?.includes('3 / 10'))).toBe(true);
    expect(statuses().some((el) => el.textContent?.includes('1 / 8'))).toBe(true);
  });

  it('shows independent progress updates per website', () => {
    const updatedJob1: CrawlJob = { ...RUNNING_JOB_1, pages_completed: 7 };
    mockedUseCrawlActivity.mockImplementation(
      (websiteId) =>
        ({
          crawlJob: websiteId === 'site-1' ? updatedJob1 : RUNNING_JOB_2,
          crawlProgress: null,
          sseConnected: false,
        }) as CrawlActivity,
    );

    renderList();

    const statuses = () => screen.getAllByRole('status');
    expect(statuses().some((el) => el.textContent?.includes('7 / 10'))).toBe(true);
    expect(statuses().some((el) => el.textContent?.includes('1 / 8'))).toBe(true);
  });

  it('does not show progress for websites whose job has finished', () => {
    // site-1's job finished (dropped by the monitor) -> no progress bar,
    // while site-2's crawl is still running.
    mockedUseCrawlActivity.mockImplementation(
      (websiteId) =>
        ({
          crawlJob: websiteId === 'site-1' ? null : RUNNING_JOB_2,
          crawlProgress: null,
          sseConnected: false,
        }) as CrawlActivity,
    );

    renderList();

    const statuses = () => screen.getAllByRole('status');
    expect(statuses().every((el) => !el.textContent?.includes('3 / 10'))).toBe(true);
    expect(statuses().some((el) => el.textContent?.includes('1 / 8'))).toBe(true);
  });
});
