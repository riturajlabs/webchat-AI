import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import { createActiveCrawlStore, type ActiveCrawlStore } from './active-crawl-store';
import { CrawlActivityProvider, useCrawlActivity } from './crawl-activity-context';
import { crawlJobKeys, useWebsites } from './hooks';
import type { CrawlJob, Website } from './types';

vi.mock('@/lib/api', () => ({
  API_BASE_URL: 'http://localhost:8000',
  api: {
    get: vi.fn(),
    post: vi.fn().mockResolvedValue({ message: 'ok' }),
  },
}));

const mockedGet = vi.mocked(api.get);

/* ------------------------------------------------------------------ */
/*  Mock EventSource                                                   */
/* ------------------------------------------------------------------ */

type ESListener = (e: MessageEvent) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ESListener[]>();

  constructor(url: string, _opts?: EventSourceInit) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: ESListener) {
    const list = this.listeners.get(type) ?? [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  removeEventListener(type: string, listener: ESListener) {
    const list = this.listeners.get(type) ?? [];
    this.listeners.set(
      type,
      list.filter((l) => l !== listener),
    );
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  triggerOpen() {
    this.readyState = 1; // OPEN
    this.onopen?.();
  }

  triggerError() {
    this.onerror?.();
  }

  triggerEvent(type: string, data: unknown) {
    const listeners = this.listeners.get(type) ?? [];
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const fn of listeners) fn(event);
  }
}

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

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
  knowledge_status: 'none',
  knowledge_documents: 0,
  knowledge_chunks: 0,
  last_knowledge_at: null,
};

const SITE2: Website = {
  ...SITE,
  id: 'site-2',
  name: 'Other Site',
  url: 'https://other.example.com',
  widget_id: 'widget-2',
};

const SITE_EMBEDDING: Website = {
  ...SITE,
  pages_indexed: 5,
  knowledge_status: 'processing',
  knowledge_documents: 2,
  knowledge_chunks: 11,
};

const SITE_READY: Website = {
  ...SITE,
  pages_indexed: 8,
  knowledge_status: 'ready',
  knowledge_documents: 4,
  knowledge_chunks: 27,
};

const JOB_RUNNING: CrawlJob = {
  id: 'job-1',
  website_id: 'site-1',
  status: 'running',
  pages_total: 5,
  pages_completed: 2,
  errors: [],
  started_at: '2026-08-01T00:00:00Z',
  completed_at: null,
  error_message: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

const JOB_COMPLETED: CrawlJob = {
  ...JOB_RUNNING,
  status: 'completed',
  pages_completed: 5,
  completed_at: '2026-08-01T00:00:05Z',
};

const JOB_FAILED: CrawlJob = {
  ...JOB_RUNNING,
  status: 'failed',
  error_message: 'Browser crashed',
};

/* ------------------------------------------------------------------ */
/*  Harness                                                            */
/* ------------------------------------------------------------------ */

interface MonitorKnobs {
  refreshIntervalMs?: number;
  knowledgeStartGraceMs?: number;
  settleCheckIntervalMs?: number;
  failureVisibilityMs?: number;
  watchdogMs?: number;
}

function SiteProbe({ id }: { id: string }) {
  const activity = useCrawlActivity(id);
  return (
    <div data-testid={`probe-${id}`}>
      {activity.crawlJob?.status ?? 'idle'}|{activity.sseConnected ? 'sse' : 'no-sse'}|
      {activity.crawlProgress?.status ?? ''}|p:{activity.crawlProgress?.pages_completed ?? ''}
    </div>
  );
}

function Probe({ websiteIds = ['site-1'] }: { websiteIds?: string[] }) {
  const { data } = useWebsites();
  const web = data?.find((w) => w.id === 'site-1');

  return (
    <div>
      {websiteIds.map((id) => (
        <SiteProbe key={id} id={id} />
      ))}
      <div data-testid="list">
        {web ? `list:${web.pages_indexed}:${web.knowledge_status}` : 'no-list'}
      </div>
    </div>
  );
}

function renderMonitor(store: ActiveCrawlStore, knobs: MonitorKnobs = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const tree = (children: ReactNode) => (
    <QueryClientProvider client={queryClient}>
      <CrawlActivityProvider
        store={store}
        refreshIntervalMs={knobs.refreshIntervalMs ?? 40}
        knowledgeStartGraceMs={knobs.knowledgeStartGraceMs ?? 1000}
        settleCheckIntervalMs={knobs.settleCheckIntervalMs ?? 30}
        failureVisibilityMs={knobs.failureVisibilityMs ?? 300}
        watchdogMs={knobs.watchdogMs ?? 4000}
      >
        {children}
      </CrawlActivityProvider>
    </QueryClientProvider>
  );

  const utils = render(tree(<Probe />));
  return {
    ...utils,
    queryClient,
    rerenderWith(child: ReactNode) {
      utils.rerender(tree(child));
    },
  };
}

function latest(): MockEventSource {
  const last = MockEventSource.instances.at(-1);
  if (!last) throw new Error('No EventSource instances created');
  return last;
}

function getCount(path: string): number {
  return mockedGet.mock.calls.filter(([callPath]) => callPath === path).length;
}

/** Simulates the next authoritative crawl-job poll observing a new status. */
async function observeJobStatus(queryClient: QueryClient, jobId: string): Promise<void> {
  await act(async () => {
    await queryClient.invalidateQueries({ queryKey: crawlJobKeys.detail(jobId) });
  });
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('CrawlActivityProvider + monitor', () => {
  let sites: Record<string, Website>;
  let jobs: Record<string, CrawlJob>;

  beforeEach(() => {
    MockEventSource.instances = [];
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.stubGlobal('EventSource', MockEventSource);

    sites = { 'site-1': { ...SITE }, 'site-2': { ...SITE2 } };
    jobs = { 'job-1': { ...JOB_RUNNING } };

    mockedGet.mockImplementation((path: string) => {
      const jobMatch = path.match(/^\/api\/crawl-jobs\/(.+)$/);
      if (jobMatch) {
        const found = jobs[jobMatch[1]!];
        return found ? Promise.resolve(found) : Promise.reject(new Error('job not found'));
      }
      if (path === '/api/websites') {
        return Promise.resolve(Object.values(sites));
      }
      const siteMatch = path.match(/^\/api\/websites\/(.+)$/);
      if (siteMatch) {
        const found = sites[siteMatch[1]!];
        return found ? Promise.resolve(found) : Promise.reject(new Error('site not found'));
      }
      return Promise.reject(new Error(`Unexpected path ${path}`));
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('streams crawl progress for a tracked job and exposes it to consumers', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    renderMonitor(store);

    const es = latest();
    expect(es.url).toBe('http://localhost:8000/api/crawl-jobs/job-1/stream');
    expect(MockEventSource.instances).toHaveLength(1);

    await act(async () => {
      es.triggerOpen();
    });
    expect(screen.getByTestId('probe-site-1')).toHaveTextContent('running|sse|');

    await act(async () => {
      es.triggerEvent('crawl.progress', {
        status: 'fetching',
        pages_completed: 3,
        pages_total: 5,
      });
    });
    expect(screen.getByTestId('probe-site-1')).toHaveTextContent('running|sse|fetching|p:3');
  });

  it('upserts polled website data into the shared list cache so pages update live', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    const { queryClient } = renderMonitor(store);

    await act(async () => {
      latest().triggerOpen();
    });
    await waitFor(() => expect(screen.getByTestId('list')).toHaveTextContent('list:0:none'));

    // The backend starts embedding; the monitor's next targeted poll pushes
    // the update straight into the ['websites'] cache that pages render.
    sites['site-1'] = { ...SITE_EMBEDDING };
    await waitFor(() => expect(screen.getByTestId('list')).toHaveTextContent('list:5:processing'));

    expect(queryClient.getQueryData<Website[]>(['websites'])).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'site-1',
          pages_indexed: 5,
          knowledge_status: 'processing',
        }),
      ]),
    );
  });

  it('subscribes exactly one SSE stream per job and never duplicates on re-render', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    store.set('site-2', 'job-2');
    jobs['job-2'] = { ...JOB_RUNNING, id: 'job-2', website_id: 'site-2' };

    const { rerenderWith } = renderMonitor(store);
    expect(MockEventSource.instances).toHaveLength(2);

    // Simulate navigating within the dashboard: the provider tree stays
    // mounted but the page content changes. No new streams are opened.
    rerenderWith(<Probe websiteIds={['site-1', 'site-2']} />);
    expect(MockEventSource.instances).toHaveLength(2);
  });

  it('completes a crawl, closes SSE, refreshes the list and drops the job once knowledge settles', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    const { queryClient } = renderMonitor(store);

    const es = latest();
    await act(async () => {
      es.triggerOpen();
    });

    // Backend finishes the crawl and queues embedding.
    await act(async () => {
      es.triggerEvent('crawl.completed', { status: 'completed' });
    });
    expect(es.readyState).toBe(2); // SSE closed
    expect(screen.getByTestId('probe-site-1')).toHaveTextContent('no-sse');

    // The next crawl-job poll observes the terminal status: list refreshed,
    // and the watcher keeps monitoring the embedding phase.
    jobs['job-1'] = { ...JOB_COMPLETED };
    sites['site-1'] = { ...SITE_EMBEDDING };
    const listFetchesBefore = getCount('/api/websites');
    await observeJobStatus(queryClient, 'job-1');

    await waitFor(() =>
      expect(screen.getByTestId('probe-site-1')).toHaveTextContent('completed|no-sse|'),
    );
    expect(store.getJobs().size).toBe(1); // still watching knowledge embedding
    await waitFor(() => expect(getCount('/api/websites')).toBeGreaterThan(listFetchesBefore));

    // Terminal invalidates both the list AND the single-website detail query;
    // the monitor's own poll pushes the embedding state into both caches so
    // no consumer is left with stale pages_indexed / knowledge_* values.
    await waitFor(() =>
      expect(queryClient.getQueryData<Website>(['website', 'site-1'])).toEqual(
        expect.objectContaining({ pages_indexed: 5, knowledge_status: 'processing' }),
      ),
    );

    // Embedding finishes; on the next watcher tick the job is dropped.
    sites['site-1'] = { ...SITE_READY };
    await waitFor(() => expect(store.getJobs().size).toBe(0));
    await waitFor(() =>
      expect(screen.getByTestId('probe-site-1')).toHaveTextContent('idle|no-sse|'),
    );

    // Both caches converge on the final authoritative state.
    await waitFor(() =>
      expect(queryClient.getQueryData<Website>(['website', 'site-1'])).toEqual(
        expect.objectContaining({ pages_indexed: 8, knowledge_status: 'ready' }),
      ),
    );
    await waitFor(() => expect(screen.getByTestId('list')).toHaveTextContent('list:8:ready'));
  });

  it('drops a completed job after the grace window when embedding never starts', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    const { queryClient } = renderMonitor(store, { knowledgeStartGraceMs: 800 });

    const es = latest();
    await act(async () => {
      es.triggerOpen();
    });
    await act(async () => {
      es.triggerEvent('crawl.completed', { status: 'completed' });
    });

    // Terminal observed, but knowledge_status stays 'none' ("no embedding
    // configured" case): the job is kept for the grace window...
    jobs['job-1'] = { ...JOB_COMPLETED };
    await observeJobStatus(queryClient, 'job-1');
    await waitFor(() =>
      expect(screen.getByTestId('probe-site-1')).toHaveTextContent('completed|no-sse|'),
    );
    expect(store.getJobs().size).toBe(1);

    // ...then dropped to avoid infinite polling.
    await waitFor(() => expect(store.getJobs().size).toBe(0), { timeout: 2000 });
    await waitFor(() =>
      expect(screen.getByTestId('probe-site-1')).toHaveTextContent('idle|no-sse|'),
    );
  });

  it('keeps a failed crawl visible long enough for retry, then stops tracking it', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    const { queryClient } = renderMonitor(store, { failureVisibilityMs: 300 });

    const es = latest();
    await act(async () => {
      es.triggerOpen();
    });
    await act(async () => {
      es.triggerEvent('crawl.failed', { status: 'failed', error: 'timeout' });
    });

    // The terminal job is observed: the failure state (Crawl failed label +
    // Retry action on the card) stays visible during the visibility window,
    // and there is no knowledge phase to wait for.
    jobs['job-1'] = { ...JOB_FAILED };
    await observeJobStatus(queryClient, 'job-1');
    await waitFor(() =>
      expect(screen.getByTestId('probe-site-1')).toHaveTextContent('failed|no-sse|'),
    );
    expect(store.getJobs().size).toBe(1); // still showing the failure UI

    // ...then the monitor drops it so nothing lingers.
    await waitFor(() => expect(store.getJobs().size).toBe(0), { timeout: 2000 });
    expect(screen.getByTestId('probe-site-1')).toHaveTextContent('idle|no-sse|');
  });

  it('keeps tracking and reconnects the SSE stream after a network failure', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    renderMonitor(store);

    const es0 = latest();
    await act(async () => {
      es0.triggerOpen();
    });
    expect(store.getJobs().size).toBe(1);

    // The stream fails; the hook schedules an automatic reconnect.
    await act(async () => {
      es0.triggerError();
    });
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(2), {
      timeout: 5000,
    });
    expect(MockEventSource.instances[1]!.url).toBe(
      'http://localhost:8000/api/crawl-jobs/job-1/stream',
    );

    // Nothing is dropped and progress keeps surfacing while the reconnect is
    // pending.
    expect(store.getJobs().size).toBe(1);
    expect(screen.getByTestId('probe-site-1')).toHaveTextContent('running|no-sse|');
  });

  it('drops the job when the crawl-job query hard-fails', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    delete jobs['job-1'];

    renderMonitor(store);

    await waitFor(() => expect(store.getJobs().size).toBe(0));
    expect(screen.getByTestId('probe-site-1')).toHaveTextContent('idle|no-sse|');
  });

  it('closes the SSE stream and stops polling when the provider unmounts', async () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    const { unmount } = renderMonitor(store);

    const es = latest();
    await act(async () => {
      es.triggerOpen();
    });
    await waitFor(() => expect(getCount('/api/websites/site-1')).toBeGreaterThan(0));

    unmount();
    expect(es.readyState).toBe(2); // closed

    // No further targeted polls fire after the watcher is gone.
    const siteFetches = getCount('/api/websites/site-1');
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(getCount('/api/websites/site-1')).toBe(siteFetches);
  });

  it('restores active jobs from sessionStorage on provider mount', () => {
    sessionStorage.setItem('webchat_active_crawl_jobs', JSON.stringify([['site-1', 'job-1']]));
    const restored = createActiveCrawlStore();
    renderMonitor(restored);

    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0]!.url).toBe(
      'http://localhost:8000/api/crawl-jobs/job-1/stream',
    );
  });
});
