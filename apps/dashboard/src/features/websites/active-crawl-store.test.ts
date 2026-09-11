import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createActiveCrawlStore } from './active-crawl-store';

const ACTIVE_JOBS_KEY = 'webchat_active_crawl_jobs';

describe('activeCrawlStore', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('starts empty and returns undefined for unknown websites', () => {
    const store = createActiveCrawlStore();
    expect(store.getJobs().size).toBe(0);
    expect(store.getJobId('site-1')).toBeUndefined();
  });

  it('tracks jobs and notifies subscribers on set and remove', () => {
    const store = createActiveCrawlStore();
    const listener = vi.fn();
    store.subscribe(listener);

    store.set('site-1', 'job-1');
    expect(store.getJobId('site-1')).toBe('job-1');
    expect(store.getJobs()).toEqual(new Map([['site-1', 'job-1']]));
    expect(listener).toHaveBeenCalledTimes(1);

    store.remove('site-1');
    expect(store.getJobs().size).toBe(0);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('does not notify when removing an unknown job', () => {
    const store = createActiveCrawlStore();
    const listener = vi.fn();
    store.subscribe(listener);

    store.remove('site-missing');
    expect(listener).not.toHaveBeenCalled();
  });

  it('persists jobs to sessionStorage and clears the entry when empty', () => {
    const store = createActiveCrawlStore();
    store.set('site-1', 'job-1');
    store.set('site-2', 'job-2');

    expect(JSON.parse(sessionStorage.getItem(ACTIVE_JOBS_KEY)!)).toEqual([
      ['site-1', 'job-1'],
      ['site-2', 'job-2'],
    ]);

    store.remove('site-1');
    store.remove('site-2');
    expect(sessionStorage.getItem(ACTIVE_JOBS_KEY)).toBeNull();
  });

  it('restores persisted jobs from sessionStorage on creation', () => {
    sessionStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify([['site-1', 'job-restored']]));
    const store = createActiveCrawlStore();
    expect(store.getJobs()).toEqual(new Map([['site-1', 'job-restored']]));
  });

  it('handles corrupted sessionStorage data gracefully', () => {
    sessionStorage.setItem(ACTIVE_JOBS_KEY, 'not-valid-json{{{');
    const store = createActiveCrawlStore();
    expect(store.getJobs().size).toBe(0);
  });

  it('handles non-array sessionStorage data gracefully', () => {
    sessionStorage.setItem(ACTIVE_JOBS_KEY, '{"unexpected": "format"}');
    const store = createActiveCrawlStore();
    expect(store.getJobs().size).toBe(0);
  });

  it('filters malformed persisted entries', () => {
    sessionStorage.setItem(
      ACTIVE_JOBS_KEY,
      JSON.stringify([['site-1', 'job-1'], 'garbage', ['site-2'], ['site-3', 'job-3']]),
    );
    const store = createActiveCrawlStore();
    expect(store.getJobs()).toEqual(
      new Map([
        ['site-1', 'job-1'],
        ['site-3', 'job-3'],
      ]),
    );
  });

  it('unsubscribing stops notifications', () => {
    const store = createActiveCrawlStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    unsubscribe();

    store.set('site-1', 'job-1');
    expect(listener).not.toHaveBeenCalled();
  });
});
