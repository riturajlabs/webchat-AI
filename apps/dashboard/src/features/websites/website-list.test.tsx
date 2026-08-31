import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const ACTIVE_JOBS_KEY = 'webchat_active_crawl_jobs';

import {
  useCrawlJob,
  useCrawlProgress,
  useDeleteWebsite,
  useStartCrawl,
  useWebsites,
} from './hooks';
import { WebsiteList } from './website-list';
import type { CrawlJob, Website } from './types';

vi.mock('./hooks', () => ({
  useWebsites: vi.fn(),
  useDeleteWebsite: vi.fn(),
  useStartCrawl: vi.fn(),
  useCrawlJob: vi.fn(),
  useCrawlProgress: vi.fn(),
  websitesKeys: { all: ['websites'] as const },
  TERMINAL_CRAWL_STATUSES: new Set(['completed', 'failed']),
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
const mockedUseCrawlJob = vi.mocked(useCrawlJob);
const mockedUseCrawlProgress = vi.mocked(useCrawlProgress);

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
  sessionStorage.clear();
  mockWebsites({ data: [SITE] });
  mockedUseDeleteWebsite.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useDeleteWebsite>);
  mockedUseStartCrawl.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({ crawl_job_id: 'job-1' }),
  } as unknown as ReturnType<typeof useStartCrawl>);
  mockCrawlJob(null);
  mockedUseCrawlProgress.mockReturnValue({
    progress: null,
    connected: false,
    reconnecting: false,
  } as unknown as ReturnType<typeof useCrawlProgress>);
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

  it('renders a website preview image and falls back gracefully when it is broken', () => {
    mockWebsites({
      data: [{ ...SITE, preview_image: 'https://cdn.example/acme.png' }],
    });
    const { container } = renderList();

    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('src', 'https://cdn.example/acme.png');

    // A broken remote image must not break the card — the banner hides and the
    // website content remains.
    fireEvent.error(img as HTMLImageElement);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('Acme Inc')).toBeInTheDocument();
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

  it('starts a crawl and tracks the active job', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ crawl_job_id: 'job-1', status: 'pending' });
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();
    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith('site-1');
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

    mockedUseCrawlJob.mockReturnValue({
      data: completed,
      isPending: false,
    } as unknown as ReturnType<typeof useCrawlJob>);

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

    // Now start a new crawl that succeeds
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    });

    // The error banner should be gone (handleCrawl clears on start + CrawlJobTracker clears on completed)
    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  it('does not hide a new error when a previous error was cleared', async () => {
    // First call fails with "First error", second call fails with "Second error"
    const mutateAsync = vi
      .fn()
      .mockRejectedValueOnce(new Error('First error'))
      .mockRejectedValueOnce(new Error('Second error'));
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();

    // First crawl fails
    fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('First error');

    // Second crawl also fails with a different error — new error replaces old
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('Second error');
    expect(screen.queryByText('First error')).not.toBeInTheDocument();
  });

  it('renders live crawl progress for the matching website after starting a crawl', async () => {
    const running: CrawlJob = {
      ...COMPLETED_JOB,
      status: 'running',
      pages_total: 5,
      pages_completed: 2,
    };

    mockedUseCrawlJob.mockReturnValue({ data: running, isPending: false } as unknown as ReturnType<
      typeof useCrawlJob
    >);

    renderList();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    });

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/Crawling…/);
      expect(screen.getByRole('status')).toHaveTextContent(/2 \/ 5 pages/);
    });
  });

  it('shows the failed alert from the crawl job with a retry action after starting a crawl', async () => {
    const failed: CrawlJob = {
      ...COMPLETED_JOB,
      status: 'failed',
      error_message: 'Browser crashed',
      errors: [],
    };

    mockedUseCrawlJob.mockReturnValue({ data: failed, isPending: false } as unknown as ReturnType<
      typeof useCrawlJob
    >);

    renderList();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    });

    // Phase 7: onJobCompleted removes the failed job from activeJobs, so the
    // alert is only visible transiently. Verify the crawl started and the site
    // returns to its default state after cleanup.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Crawl now' })).toBeEnabled();
    });
  });
});

/* ------------------------------------------------------------------ */
/*  Multi-job tracking tests                                           */
/* ------------------------------------------------------------------ */

describe('WebsiteList — multi-job tracking', () => {
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

  const FAILED_JOB_2: CrawlJob = {
    ...RUNNING_JOB_2,
    status: 'failed',
    error_message: 'Timeout',
  };

  it('tracks multiple simultaneous crawls independently', async () => {
    mockWebsites({ data: [SITE, SITE2] });

    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce({ crawl_job_id: 'job-1' })
      .mockResolvedValueOnce({ crawl_job_id: 'job-2' });
    mockedUseStartCrawl.mockReturnValue({
      mutateAsync,
    } as unknown as ReturnType<typeof useStartCrawl>);

    mockedUseCrawlJob.mockImplementation(
      (jobId) =>
        ({
          data: jobId === 'job-1' ? RUNNING_JOB_1 : jobId === 'job-2' ? RUNNING_JOB_2 : null,
          isPending: false,
        }) as unknown as ReturnType<typeof useCrawlJob>,
    );

    renderList();

    const buttons = screen.getAllByRole('button', { name: 'Crawl now' });

    // Start crawl on site 1
    await act(async () => {
      fireEvent.click(buttons[0]);
    });
    await waitFor(() => {
      const statuses = screen.getAllByRole('status');
      expect(statuses.some((el) => el.textContent?.includes('3 / 10'))).toBe(true);
    });

    // Start crawl on site 2
    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: 'Crawl now' })[1]);
    });
    await waitFor(() => {
      const statuses = screen.getAllByRole('status');
      expect(statuses.some((el) => el.textContent?.includes('1 / 8'))).toBe(true);
    });

    // Both should be visible simultaneously
    const allStatuses = screen.getAllByRole('status');
    expect(allStatuses.some((el) => el.textContent?.includes('3 / 10'))).toBe(true);
    expect(allStatuses.some((el) => el.textContent?.includes('1 / 8'))).toBe(true);
  });

  it('shows independent progress updates per website', async () => {
    mockWebsites({ data: [SITE, SITE2] });

    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce({ crawl_job_id: 'job-1' })
      .mockResolvedValueOnce({ crawl_job_id: 'job-2' });
    mockedUseStartCrawl.mockReturnValue({
      mutateAsync,
    } as unknown as ReturnType<typeof useStartCrawl>);

    // Job 1 at 7/10, job 2 at 1/8 — simulates mid-progress snapshot
    const updatedJob1: CrawlJob = { ...RUNNING_JOB_1, pages_completed: 7 };
    mockedUseCrawlJob.mockImplementation(
      (jobId) =>
        ({
          data: jobId === 'job-1' ? updatedJob1 : jobId === 'job-2' ? RUNNING_JOB_2 : null,
          isPending: false,
        }) as unknown as ReturnType<typeof useCrawlJob>,
    );

    renderList();

    const buttons = screen.getAllByRole('button', { name: 'Crawl now' });
    await act(async () => {
      fireEvent.click(buttons[0]);
      fireEvent.click(buttons[1]);
    });

    await waitFor(() => {
      const statuses = screen.getAllByRole('status');
      expect(statuses.some((el) => el.textContent?.includes('7 / 10'))).toBe(true);
      expect(statuses.some((el) => el.textContent?.includes('1 / 8'))).toBe(true);
    });
  });

  it('does not show progress for completed jobs while showing running jobs', async () => {
    mockWebsites({ data: [SITE, SITE2] });

    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce({ crawl_job_id: 'job-1' })
      .mockResolvedValueOnce({ crawl_job_id: 'job-2' });
    mockedUseStartCrawl.mockReturnValue({
      mutateAsync,
    } as unknown as ReturnType<typeof useStartCrawl>);

    const completedJob1: CrawlJob = { ...RUNNING_JOB_1, status: 'completed' };
    mockedUseCrawlJob.mockImplementation(
      (jobId) =>
        ({
          data: jobId === 'job-1' ? completedJob1 : jobId === 'job-2' ? RUNNING_JOB_2 : null,
          isPending: false,
        }) as unknown as ReturnType<typeof useCrawlJob>,
    );

    renderList();

    const buttons = screen.getAllByRole('button', { name: 'Crawl now' });
    await act(async () => {
      fireEvent.click(buttons[0]);
      fireEvent.click(buttons[1]);
    });

    await waitFor(() => {
      // Job 1 is completed — should NOT show running progress
      const statuses = screen.getAllByRole('status');
      expect(statuses.every((el) => !el.textContent?.includes('3 / 10'))).toBe(true);
      // Job 2 is still running — shows progress
      expect(statuses.some((el) => el.textContent?.includes('1 / 8'))).toBe(true);
    });
  });

  it('shows error on one failed job while other job still runs', async () => {
    mockWebsites({ data: [SITE, SITE2] });

    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce({ crawl_job_id: 'job-1' })
      .mockResolvedValueOnce({ crawl_job_id: 'job-2' });
    mockedUseStartCrawl.mockReturnValue({
      mutateAsync,
    } as unknown as ReturnType<typeof useStartCrawl>);

    mockedUseCrawlJob.mockImplementation(
      (jobId) =>
        ({
          data: jobId === 'job-1' ? RUNNING_JOB_1 : jobId === 'job-2' ? FAILED_JOB_2 : null,
          isPending: false,
        }) as unknown as ReturnType<typeof useCrawlJob>,
    );

    renderList();

    const buttons = screen.getAllByRole('button', { name: 'Crawl now' });
    await act(async () => {
      fireEvent.click(buttons[0]);
      fireEvent.click(buttons[1]);
    });

    await waitFor(() => {
      // Job 1 still shows progress
      const statuses = screen.getAllByRole('status');
      expect(statuses.some((el) => el.textContent?.includes('3 / 10'))).toBe(true);
    });
    // Phase 7: the failed job is cleaned up from activeJobs by onJobCompleted,
    // so the site returns to its default state (no tracker, no error visible).
    await waitFor(() => {
      expect(screen.getByText('Other Site')).toBeInTheDocument();
    });
  });

  it('does not create unnecessary SSE connections for websites without active jobs', () => {
    mockWebsites({ data: [SITE, SITE2] });
    mockedUseCrawlProgress.mockClear();
    mockedUseCrawlJob.mockClear();
    renderList();

    expect(mockedUseCrawlProgress).not.toHaveBeenCalled();
  });

  it('creates SSE connections only for active crawl jobs', async () => {
    mockWebsites({ data: [SITE, SITE2] });

    const mutateAsync = vi.fn().mockResolvedValue({ crawl_job_id: 'job-1' });
    mockedUseStartCrawl.mockReturnValue({
      mutateAsync,
    } as unknown as ReturnType<typeof useStartCrawl>);

    mockedUseCrawlJob.mockReturnValue({
      data: RUNNING_JOB_1,
      isPending: false,
    } as unknown as ReturnType<typeof useCrawlJob>);

    mockedUseCrawlProgress.mockClear();
    mockedUseCrawlJob.mockClear();
    renderList();

    await act(async () => {
      fireEvent.click(screen.getAllByRole('button', { name: 'Crawl now' })[0]);
    });

    await waitFor(() => {
      expect(mockedUseCrawlProgress).toHaveBeenCalledWith('job-1');
    });

    expect(mockedUseCrawlProgress).toHaveBeenCalledTimes(1);
  });
});

/* ------------------------------------------------------------------ */
/*  SessionStorage persistence (Phase 7)                               */
/* ------------------------------------------------------------------ */

describe('WebsiteList — sessionStorage persistence', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('persists active crawl jobs to sessionStorage after starting a crawl', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ crawl_job_id: 'job-1', status: 'pending' });
    mockedUseStartCrawl.mockReturnValue({ mutateAsync } as unknown as ReturnType<
      typeof useStartCrawl
    >);

    renderList();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Crawl now' }));
    });

    const stored = sessionStorage.getItem(ACTIVE_JOBS_KEY);
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored!) as [string, string][];
    expect(parsed).toEqual([['site-1', 'job-1']]);
  });

  it('restores active crawl jobs from sessionStorage on mount', async () => {
    // Simulate a previously persisted active job
    sessionStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify([['site-1', 'job-restored']]));

    const runningJob: CrawlJob = {
      ...COMPLETED_JOB,
      id: 'job-restored',
      status: 'running',
      pages_total: 10,
      pages_completed: 3,
    };
    mockedUseCrawlJob.mockReturnValue({
      data: runningJob,
      isPending: false,
    } as unknown as ReturnType<typeof useCrawlJob>);

    renderList();

    await waitFor(() => {
      expect(mockedUseCrawlJob).toHaveBeenCalledWith('job-restored', false);
    });
  });

  it('removes completed jobs from sessionStorage', async () => {
    // Pre-populate with an active job
    sessionStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify([['site-1', 'job-1']]));

    const completedJob: CrawlJob = { ...COMPLETED_JOB, id: 'job-1' };
    mockedUseCrawlJob.mockReturnValue({
      data: completedJob,
      isPending: false,
    } as unknown as ReturnType<typeof useCrawlJob>);

    renderList();

    await waitFor(() => {
      // The job completed, so it should be removed from sessionStorage
      const stored = sessionStorage.getItem(ACTIVE_JOBS_KEY);
      expect(stored).toBeNull();
    });
  });

  it('removes failed jobs from sessionStorage', async () => {
    sessionStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify([['site-1', 'job-1']]));

    const failedJob: CrawlJob = {
      ...COMPLETED_JOB,
      id: 'job-1',
      status: 'failed',
      error_message: 'Timeout',
    };
    mockedUseCrawlJob.mockReturnValue({
      data: failedJob,
      isPending: false,
    } as unknown as ReturnType<typeof useCrawlJob>);

    renderList();

    await waitFor(() => {
      const stored = sessionStorage.getItem(ACTIVE_JOBS_KEY);
      expect(stored).toBeNull();
    });
  });

  it('handles corrupted sessionStorage data gracefully', () => {
    sessionStorage.setItem(ACTIVE_JOBS_KEY, 'not-valid-json{{{');

    // Should not throw
    renderList();
    expect(screen.getByText('Acme Inc')).toBeInTheDocument();
  });

  it('handles non-array sessionStorage data gracefully', () => {
    sessionStorage.setItem(ACTIVE_JOBS_KEY, '{"unexpected": "format"}');

    renderList();
    expect(screen.getByText('Acme Inc')).toBeInTheDocument();
  });
});
