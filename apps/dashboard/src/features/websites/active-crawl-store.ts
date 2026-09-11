/**
 * App-wide registry of "live" crawl jobs, keyed by website id.
 *
 * This replaced the page-local sessionStorage tracking that used to live
 * inside `website-list.tsx` (Phase 7). Any component can start, stop or query
 * an active crawl job, and the dashboard-wide `CrawlActivityProvider` (see
 * `crawl-activity-context.tsx`) subscribes so that exactly one SSE stream +
 * one job poll exists per running crawl regardless of which page is open.
 *
 * Persistence format (unchanged from Phase 7): a JSON array of `[websiteId,
 * jobId]` pairs under `webchat_active_crawl_jobs`, so the tracking survives a
 * full page reload (the job itself keeps running server-side).
 */

const ACTIVE_JOBS_KEY = 'webchat_active_crawl_jobs';

export interface ActiveCrawlStore {
  /** Current map of websiteId -> jobId. */
  getJobs(): Map<string, string>;
  /** Job id currently tracking `websiteId`, or undefined. */
  getJobId(websiteId: string): string | undefined;
  set(websiteId: string, jobId: string): void;
  remove(websiteId: string): void;
  /** Subscribe to changes; returns an unsubscribe function. */
  subscribe(listener: () => void): () => void;
}

function loadJobs(): Map<string, string> {
  try {
    const raw = sessionStorage.getItem(ACTIVE_JOBS_KEY);
    if (!raw) return new Map();
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return new Map(
        parsed.filter((entry): entry is [string, string] => {
          return Array.isArray(entry) && entry.length === 2 && typeof entry[0] === 'string';
        }),
      );
    }
    return new Map();
  } catch {
    return new Map();
  }
}

function persistJobs(jobs: Map<string, string>): void {
  try {
    if (jobs.size === 0) {
      sessionStorage.removeItem(ACTIVE_JOBS_KEY);
    } else {
      sessionStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify([...jobs]));
    }
  } catch {
    // sessionStorage may be unavailable; silently ignore.
  }
}

export function createActiveCrawlStore(): ActiveCrawlStore {
  const jobs = loadJobs();
  const listeners = new Set<() => void>();

  function notify(): void {
    for (const listener of listeners) {
      listener();
    }
  }

  return {
    getJobs() {
      return new Map(jobs);
    },
    getJobId(websiteId: string) {
      return jobs.get(websiteId);
    },
    set(websiteId: string, jobId: string) {
      jobs.set(websiteId, jobId);
      persistJobs(jobs);
      notify();
    },
    remove(websiteId: string) {
      if (!jobs.has(websiteId)) {
        return;
      }
      jobs.delete(websiteId);
      persistJobs(jobs);
      notify();
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/** The application-wide store used by the provider and consumers. */
export const activeCrawlStore = createActiveCrawlStore();
