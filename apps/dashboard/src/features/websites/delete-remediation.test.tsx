import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import { knowledgeKeys, useKnowledgeReadinessForSites } from '@/features/knowledge/hooks';
import type { KnowledgeDocumentsResponse } from '@/features/knowledge/types';

import { activeCrawlStore, type ActiveCrawlStore } from './active-crawl-store';
import { CrawlActivityProvider } from './crawl-activity-context';
import { useDeleteWebsite, useWebsites } from './hooks';
import type { CrawlJob, Website } from './types';

vi.mock('@/lib/api', () => ({
  API_BASE_URL: 'http://localhost:8000',
  api: {
    get: vi.fn(),
    post: vi.fn().mockResolvedValue({ message: 'ok' }),
    delete: vi.fn().mockResolvedValue(undefined),
  },
}));

const mockedGet = vi.mocked(api.get);
const mockedDelete = vi.mocked(api.delete);

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

  triggerEvent(type: string, data: unknown) {
    const listeners = this.listeners.get(type) ?? [];
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const fn of listeners) fn(event);
  }

  triggerError() {
    this.onerror?.();
  }
}

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

const SITE_A: Website = {
  id: 'site-a',
  tenant_id: 'tenant-1',
  name: 'Acme Inc',
  url: 'https://acme.example.com',
  status: 'ready',
  pages_indexed: 12,
  last_crawled_at: null,
  checksum: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  widget_id: 'widget-a',
  knowledge_status: 'ready',
  knowledge_documents: 3,
  knowledge_chunks: 27,
  last_knowledge_at: null,
};

const SITE_B: Website = {
  ...SITE_A,
  id: 'site-b',
  name: 'Other Site',
  url: 'https://other.example.com',
  widget_id: 'widget-b',
};

const JOB_A: CrawlJob = {
  id: 'job-a',
  website_id: 'site-a',
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

const JOB_B: CrawlJob = {
  ...JOB_A,
  id: 'job-b',
  website_id: 'site-b',
};

const docsSettled: KnowledgeDocumentsResponse = {
  website_id: 'site-a',
  summary: {
    total: 43,
    pending: 0,
    processing: 0,
    completed: 43,
    failed: 0,
    rate_limited: 0,
  },
  documents: [],
};

/* ------------------------------------------------------------------ */
/*  Harness                                                            */
/* ------------------------------------------------------------------ */

function ListProbe() {
  const { data } = useWebsites();
  const deleteWebsite = useDeleteWebsite();
  const sites = data ?? [];
  // Mirrors the real surfaces (website card / knowledge page): the readiness
  // derivation observes each listed website's documents query.
  useKnowledgeReadinessForSites(sites);
  return (
    <ul>
      {sites.map((site) => (
        <li key={site.id} data-testid={`row-${site.id}`}>
          <span>{site.name}</span>
          <button
            type="button"
            onClick={() => {
              void deleteWebsite.mutateAsync(site.id).catch(() => {});
            }}
          >
            Delete {site.name}
          </button>
        </li>
      ))}
    </ul>
  );
}

function renderApp(options: { withProvider?: boolean; store?: ActiveCrawlStore } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const body = <ListProbe />;
  const tree = (
    <QueryClientProvider client={queryClient}>
      {options.withProvider ? (
        <CrawlActivityProvider store={options.store ?? activeCrawlStore}>
          {body}
        </CrawlActivityProvider>
      ) : (
        body
      )}
    </QueryClientProvider>
  );
  const utils = render(tree);
  return { ...utils, queryClient };
}

function getCount(path: string): number {
  return mockedGet.mock.calls.filter(([callPath]) => callPath === path).length;
}

function stripStore() {
  // Reset the app-wide singleton so tests never leak tracked websites.
  activeCrawlStore.getJobs().forEach((_, websiteId) => activeCrawlStore.remove(websiteId));
  sessionStorage.clear();
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('document query cleanup on website deletion', () => {
  let sites: Record<string, Website>;
  let docs: Record<string, KnowledgeDocumentsResponse>;
  let jobs: Record<string, CrawlJob>;

  beforeEach(() => {
    MockEventSource.instances = [];
    vi.clearAllMocks();
    stripStore();
    vi.stubGlobal('EventSource', MockEventSource);

    sites = { 'site-a': { ...SITE_A }, 'site-b': { ...SITE_B } };
    docs = {
      'site-a': { ...docsSettled, website_id: 'site-a' },
      'site-b': { ...docsSettled, website_id: 'site-b' },
    };
    jobs = { 'job-a': { ...JOB_A }, 'job-b': { ...JOB_B } };

    // Deletion mirrors the backend: the deleted website leaves the list.
    mockedDelete.mockImplementation((path: string) => {
      const match = path.match(/^\/api\/websites\/(.+)$/);
      if (match && match[1] in sites) {
        delete sites[match[1]!];
      }
      return Promise.resolve(undefined);
    });
    mockedGet.mockImplementation((path: string) => {
      const jobMatch = path.match(/^\/api\/crawl-jobs\/(.+)$/);
      if (jobMatch) {
        return Promise.resolve(jobs[jobMatch[1]!]);
      }
      const docMatch = path.match(/^\/api\/knowledge\/websites\/(.+)\/documents$/);
      if (docMatch) {
        return Promise.resolve(docs[docMatch[1]!]);
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
    stripStore();
  });

  it('does not leave the deleted website documents query active and evicts its cache', async () => {
    const { queryClient } = renderApp();
    // Simulate a detail view having loaded the single-website cache too.
    queryClient.setQueryData(['website', 'site-a'], { ...SITE_A });
    queryClient.setQueryData(['website', 'site-b'], { ...SITE_B });

    // Both websites fetch documents normally (requirement D).
    await waitFor(() => expect(getCount('/api/knowledge/websites/site-a/documents')).toBe(1));
    await waitFor(() => expect(getCount('/api/knowledge/websites/site-b/documents')).toBe(1));
    expect(queryClient.getQueryData(knowledgeKeys.documents('site-a'))).toBeTruthy();
    expect(queryClient.getQueryData(knowledgeKeys.documents('site-b'))).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Delete Acme Inc' }));

    // Requirement A: the documents query for the deleted website is
    // cancelled/evicted and never fires again.
    await waitFor(() =>
      expect(queryClient.getQueryData(knowledgeKeys.documents('site-a'))).toBeUndefined(),
    );
    await waitFor(() => expect(getCount('/api/knowledge/websites/site-a/documents')).toBe(1));
    expect(screen.queryByTestId('row-site-a')).not.toBeInTheDocument();

    // The website detail cache entry is evicted too (scoped to the deleted site).
    await waitFor(() => expect(queryClient.getQueryData(['website', 'site-a'])).toBeUndefined());
    expect(queryClient.getQueryData(['website', 'site-b'])).toEqual(
      expect.objectContaining(SITE_B),
    );

    // Requirement B: website B's documents query is untouched.
    expect(queryClient.getQueryData(knowledgeKeys.documents('site-b'))).toBeTruthy();
    expect(screen.queryByTestId('row-site-b')).toBeInTheDocument();
    expect(getCount('/api/knowledge/websites/site-b/documents')).toBe(1);
  });

  it('does not clean up on a failed deletion', async () => {
    mockedDelete.mockRejectedValueOnce(new Error('boom'));
    const { queryClient } = renderApp();
    queryClient.setQueryData(['website', 'site-a'], { ...SITE_A });
    queryClient.setQueryData(knowledgeKeys.documents('site-a'), { ...docsSettled });

    await waitFor(() => expect(getCount('/api/knowledge/websites/site-a/documents')).toBe(1));

    fireEvent.click(screen.getByRole('button', { name: 'Delete Acme Inc' }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('row-site-a')).toBeInTheDocument());
    // Nothing was cleaned up when the mutation failed: the list, the website
    // detail cache and the documents cache all stay intact.
    expect(queryClient.getQueryData(['websites'])).toEqual(
      expect.arrayContaining([expect.objectContaining({ id: 'site-a' })]),
    );
    expect(queryClient.getQueryData(['website', 'site-a'])).toEqual(
      expect.objectContaining(SITE_A),
    );
    expect(queryClient.getQueryData(knowledgeKeys.documents('site-a'))).toBeTruthy();
  });

  it('stops the crawl watcher (SSE + polls) for the deleted website but keeps others', async () => {
    activeCrawlStore.set('site-a', 'job-a');
    activeCrawlStore.set('site-b', 'job-b');
    const { queryClient } = renderApp({ withProvider: true, store: activeCrawlStore });

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(2));
    const esA = MockEventSource.instances.find((es) => es.url.endsWith('/job-a/stream'));
    const esB = MockEventSource.instances.find((es) => es.url.endsWith('/job-b/stream'));
    expect(esA).toBeTruthy();
    expect(esB).toBeTruthy();
    await act(async () => {
      esA!.triggerOpen();
      esB!.triggerOpen();
    });

    // Requirement C: after deleting site A, its watcher is dropped while
    // site B's watcher keeps tracking.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Delete Acme Inc' })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Delete Acme Inc' }));

    await waitFor(() => expect(activeCrawlStore.getJobId('site-a')).toBeUndefined());
    expect(activeCrawlStore.getJobId('site-b')).toBe('job-b');
    expect(esA!.readyState).toBe(2); // SSE closed
    expect(esB!.readyState).toBe(1); // still open
    expect(queryClient.getQueryData(['crawl-job', 'job-a'])).toBeUndefined();
    expect(queryClient.getQueryData(['crawl-job', 'job-b'])).toBeTruthy();
  });
});
