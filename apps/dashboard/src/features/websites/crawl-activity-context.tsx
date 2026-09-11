'use client';

/**
 * App-wide crawl-activity tracking.
 *
 * `CrawlActivityProvider` (mounted in the authenticated dashboard layout)
 * reads active crawl jobs from `activeCrawlStore` and runs exactly one
 * `CrawlJobSync` per job: one SSE stream (`useCrawlProgress`), one authoritative
 * job query (`useCrawlJob`, which polls while SSE is down) and one targeted
 * single-website poll (`useWebsite`). Every dashboard page reads the resulting
 * live state through `useCrawlActivity(websiteId)` instead of subscribing to
 * the crawl hooks itself — no duplicate SSE connections or timers, and the UI
 * reflects backend progress (crawl, then knowledge embedding, then settled)
 * without manual refresh or navigation.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { activeCrawlStore, type ActiveCrawlStore } from './active-crawl-store';
import {
  crawlJobKeys,
  TERMINAL_CRAWL_STATUSES,
  useCrawlJob,
  useCrawlProgress,
  useWebsite,
  websiteKeys,
  websitesKeys,
} from './hooks';
import type { CrawlJob, CrawlProgressEvent, Website } from './types';

/** How often live website data is refreshed while an operation is active. */
export const CRAWL_ACTIVITY_REFRESH_MS = 3_000;

/**
 * After a crawl reaches a terminal state, the knowledge embedding phase is
 * enqueued asynchronously (its fan-out job sets `knowledge_status` to
 * 'processing' only once it starts). Keep watching for this grace window
 * before deciding no embedding will happen and dropping the job.
 */
export const KNOWLEDGE_START_GRACE_MS = 60_000;

/** How often the terminal watcher re-evaluates the knowledge phase. */
export const SETTLE_CHECK_INTERVAL_MS = 1_000;

/** Hard fail-safe cap — a stuck backend can never cause infinite polling. */
export const WATCHDOG_MS = 3_600_000;

/**
 * How long a failed crawl stays visible on the UI before the monitor stops
 * tracking it. A failed crawl has no knowledge phase, so the watcher drops it
 * quickly, but the card renders "Crawl failed" + a "Retry crawl" action from
 * the live job — keep that visible long enough to be actionable, then clean
 * up so the monitor never lingers.
 */
export const FAILURE_VISIBILITY_MS = 10_000;

export interface CrawlActivity {
  crawlJob: CrawlJob | null;
  crawlProgress: CrawlProgressEvent | null;
  sseConnected: boolean;
}

interface CrawlActivityContextValue {
  activities: ReadonlyMap<string, CrawlActivity>;
  register: (websiteId: string, activity: CrawlActivity) => void;
  unregister: (websiteId: string) => void;
  store: ActiveCrawlStore;
}

const CrawlActivityContext = createContext<CrawlActivityContextValue | null>(null);

const EMPTY_ACTIVITY: CrawlActivity = {
  crawlJob: null,
  crawlProgress: null,
  sseConnected: false,
};

function useCrawlActivityContext(): CrawlActivityContextValue {
  const context = useContext(CrawlActivityContext);
  if (!context) {
    throw new Error('CrawlActivityProvider is missing.');
  }
  return context;
}

/** Live crawl state for `websiteId`, or an empty activity while idle. */
export function useCrawlActivity(websiteId: string): CrawlActivity {
  const context = useCrawlActivityContext();
  return context.activities.get(websiteId) ?? EMPTY_ACTIVITY;
}

/* ------------------------------------------------------------------ */
/*  CrawlJobSync — one watcher per active job                          */
/* ------------------------------------------------------------------ */

function isWebsiteSettled(status: Website['knowledge_status'] | undefined): boolean {
  return status === 'ready' || status === 'failed';
}

function CrawlJobSync({
  websiteId,
  jobId,
  store,
  refreshIntervalMs,
  knowledgeStartGraceMs,
  settleCheckIntervalMs,
  failureVisibilityMs,
  watchdogMs,
}: {
  websiteId: string;
  jobId: string;
  store: ActiveCrawlStore;
  refreshIntervalMs: number;
  knowledgeStartGraceMs: number;
  settleCheckIntervalMs: number;
  failureVisibilityMs: number;
  watchdogMs: number;
}) {
  const queryClient = useQueryClient();
  const { register, unregister } = useCrawlActivityContext();

  const { progress, connected } = useCrawlProgress(jobId);
  const crawlJobQuery = useCrawlJob(jobId, connected);
  const crawlJob = crawlJobQuery.data ?? null;
  const terminal = crawlJob !== null && TERMINAL_CRAWL_STATUSES.has(crawlJob.status);

  const websiteQuery = useWebsite(websiteId, {
    refetchInterval: terminal
      ? (query) =>
          isWebsiteSettled(query.state.data?.knowledge_status) ? false : refreshIntervalMs
      : refreshIntervalMs,
  });
  const website = websiteQuery.data;

  // Expose this job's state to consumers on every dashboard page.
  const activity: CrawlActivity = useMemo(
    () => ({ crawlJob, crawlProgress: progress, sseConnected: connected }),
    [crawlJob, progress, connected],
  );
  useEffect(() => {
    register(websiteId, activity);
    return () => unregister(websiteId);
  }, [websiteId, register, unregister, activity]);

  // Keep the shared ['websites'] list cache warm, so pages that render the
  // website list / knowledge stat cards update without a manual refresh.
  useEffect(() => {
    if (!website) return;
    queryClient.setQueryData<Website[]>(websitesKeys.all, (current) => {
      if (!current) return current;
      const index = current.findIndex((entry) => entry.id === website.id);
      if (index === -1) return current;
      const next = [...current];
      next[index] = website;
      return next;
    });
  }, [website, queryClient]);

  const finish = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
    // Keep the single-website detail cache in sync with the list cache, so
    // any detail view shows the final authoritative values too.
    void queryClient.invalidateQueries({ queryKey: websiteKeys.detail(websiteId) });
    queryClient.removeQueries({ queryKey: crawlJobKeys.detail(jobId) });
    store.remove(websiteId);
  }, [queryClient, jobId, websiteId, store]);

  // A hard crawl-job query failure (backend pruned the job) means there is no
  // authoritative progress anymore — stop tracking so the UI never sticks.
  useEffect(() => {
    if (crawlJobQuery.isError) {
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
      void queryClient.invalidateQueries({ queryKey: websiteKeys.detail(websiteId) });
      store.remove(websiteId);
    }
  }, [crawlJobQuery.isError, queryClient, websiteId, store]);

  const stateRef = useRef({
    jobFailed: crawlJob?.status === 'failed',
    settle: isWebsiteSettled(website?.knowledge_status),
    knowledgeStatus: website?.knowledge_status,
  });
  stateRef.current = {
    jobFailed: crawlJob?.status === 'failed',
    settle: isWebsiteSettled(website?.knowledge_status),
    knowledgeStatus: website?.knowledge_status,
  };

  const finishRef = useRef(finish);
  finishRef.current = finish;

  const terminalAtRef = useRef<number | null>(null);
  const terminalHandledRef = useRef(false);

  // Terminal handling: refresh the authoritative list (and the single-website
  // detail) once, then keep watching while the knowledge base is still
  // embedding. A failed crawl has no knowledge phase — it is kept long enough
  // for the failure + retry UI to be visible, then dropped. A completed crawl
  // is dropped once its knowledge phase settles, or after a grace period if
  // it never starts.
  useEffect(() => {
    if (!terminal) {
      terminalHandledRef.current = false;
      terminalAtRef.current = null;
      return;
    }
    if (!terminalHandledRef.current) {
      terminalHandledRef.current = true;
      terminalAtRef.current = Date.now();
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
      void queryClient.invalidateQueries({ queryKey: websiteKeys.detail(websiteId) });
    }
    const id = setInterval(() => {
      const { jobFailed, settle, knowledgeStatus } = stateRef.current;
      if (settle) {
        finishRef.current();
      } else if (
        jobFailed &&
        terminalAtRef.current !== null &&
        Date.now() - terminalAtRef.current > failureVisibilityMs
      ) {
        finishRef.current();
      } else if (
        terminalAtRef.current !== null &&
        knowledgeStatus !== 'processing' &&
        Date.now() - terminalAtRef.current > knowledgeStartGraceMs
      ) {
        finishRef.current();
      }
    }, settleCheckIntervalMs);
    return () => clearInterval(id);
  }, [
    terminal,
    queryClient,
    websiteId,
    knowledgeStartGraceMs,
    settleCheckIntervalMs,
    failureVisibilityMs,
  ]);

  // Hard watchdog: regardless of backend behaviour, the watcher terminates.
  useEffect(() => {
    const id = setTimeout(() => finishRef.current(), watchdogMs);
    return () => clearTimeout(id);
  }, [watchdogMs]);

  return null;
}

/* ------------------------------------------------------------------ */
/*  Provider                                                           */
/* ------------------------------------------------------------------ */

export function CrawlActivityProvider({
  children,
  store = activeCrawlStore,
  refreshIntervalMs = CRAWL_ACTIVITY_REFRESH_MS,
  knowledgeStartGraceMs = KNOWLEDGE_START_GRACE_MS,
  settleCheckIntervalMs = SETTLE_CHECK_INTERVAL_MS,
  failureVisibilityMs = FAILURE_VISIBILITY_MS,
  watchdogMs = WATCHDOG_MS,
}: {
  children: ReactNode;
  store?: ActiveCrawlStore;
  refreshIntervalMs?: number;
  knowledgeStartGraceMs?: number;
  settleCheckIntervalMs?: number;
  failureVisibilityMs?: number;
  watchdogMs?: number;
}) {
  const [jobs, setJobs] = useState<Map<string, string>>(() => store.getJobs());
  const [activities, setActivities] = useState<Map<string, CrawlActivity>>(new Map());

  useEffect(() => {
    const unsubscribe = store.subscribe(() => {
      setJobs(store.getJobs());
    });
    return unsubscribe;
  }, [store]);

  const register = useCallback((websiteId: string, activity: CrawlActivity) => {
    setActivities((prev) => {
      const next = new Map(prev);
      next.set(websiteId, activity);
      return next;
    });
  }, []);

  const unregister = useCallback((websiteId: string) => {
    setActivities((prev) => {
      if (!prev.has(websiteId)) {
        return prev;
      }
      const next = new Map(prev);
      next.delete(websiteId);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ activities, register, unregister, store }),
    [activities, register, unregister, store],
  );

  return (
    <CrawlActivityContext.Provider value={value}>
      {[...jobs.entries()].map(([websiteId, jobId]) => (
        <CrawlJobSync
          key={websiteId}
          websiteId={websiteId}
          jobId={jobId}
          store={store}
          refreshIntervalMs={refreshIntervalMs}
          knowledgeStartGraceMs={knowledgeStartGraceMs}
          settleCheckIntervalMs={settleCheckIntervalMs}
          failureVisibilityMs={failureVisibilityMs}
          watchdogMs={watchdogMs}
        />
      ))}
      {children}
    </CrawlActivityContext.Provider>
  );
}
