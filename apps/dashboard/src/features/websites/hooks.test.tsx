import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useCrawlProgress } from './hooks';

vi.mock('@/lib/api', () => ({
  API_BASE_URL: 'http://localhost:8000',
  api: new Proxy(
    {},
    {
      get: (_target: object, prop: string | symbol) =>
        typeof prop === 'string'
          ? () => {
              throw new Error(`api.${prop} not mocked`);
            }
          : undefined,
    },
  ),
}));

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

  /* ---- test helpers ---- */

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
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('useCrawlProgress', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockEventSource.instances = [];
    vi.stubGlobal('EventSource', MockEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function latestInstance(): MockEventSource {
    const last = MockEventSource.instances.at(-1);
    if (!last) throw new Error('No EventSource instances created');
    return last;
  }

  it('connects to the correct URL and sets connected on open', () => {
    const { result } = renderHook(() => useCrawlProgress('job-1'));

    expect(result.current.connected).toBe(false);

    act(() => {
      latestInstance().triggerOpen();
    });

    expect(result.current.connected).toBe(true);
    expect(latestInstance().url).toBe('http://localhost:8000/api/crawl-jobs/job-1/stream');
  });

  it('does nothing when jobId is null', () => {
    renderHook(() => useCrawlProgress(null));

    expect(MockEventSource.instances).toHaveLength(0);
  });

  it('parses crawl.progress events into progress state', () => {
    const { result } = renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    act(() => {
      latestInstance().triggerEvent('crawl.progress', {
        status: 'fetching',
        pages_completed: 3,
        pages_total: 10,
      });
    });

    expect(result.current.progress).toEqual({
      status: 'fetching',
      pages_completed: 3,
      pages_total: 10,
    });
  });

  it('disconnects on crawl.completed event', () => {
    const { result } = renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    act(() => {
      latestInstance().triggerEvent('crawl.completed', { status: 'completed' });
    });

    expect(result.current.connected).toBe(false);
  });

  it('disconnects on crawl.failed event', () => {
    const { result } = renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    act(() => {
      latestInstance().triggerEvent('crawl.failed', { status: 'failed', error: 'timeout' });
    });

    expect(result.current.connected).toBe(false);
  });

  /* ------------------------------------------------------------------ */
  /*  Reconnection                                                      */
  /* ------------------------------------------------------------------ */

  it('reconnects with 2 s delay after first error', () => {
    renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    act(() => {
      latestInstance().triggerError();
    });

    // Not yet reconnected
    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1_999);
    });
    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockEventSource.instances).toHaveLength(2);
  });

  it('doubles delay on second retry (4 s)', () => {
    renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    // First error → retry 1 at 2 s
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(MockEventSource.instances).toHaveLength(2);

    // Second error → retry 2 at 4 s
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(3_999);
    });
    expect(MockEventSource.instances).toHaveLength(2);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockEventSource.instances).toHaveLength(3);
  });

  it('doubles delay on third retry (8 s)', () => {
    renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    // retry 1
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(2_000);
    });

    // retry 2
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(4_000);
    });

    // retry 3 → delay 8 s
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(7_999);
    });
    expect(MockEventSource.instances).toHaveLength(3);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockEventSource.instances).toHaveLength(4);
  });

  it('stops reconnecting after max retries (3)', () => {
    renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    // exhaust 3 retries
    for (let i = 0; i < 3; i++) {
      act(() => {
        latestInstance().triggerError();
      });
      const delay = 2_000 * 2 ** i;
      act(() => {
        vi.advanceTimersByTime(delay);
      });
    }

    const countAfterRetries = MockEventSource.instances.length;

    // a 4th error should NOT trigger another reconnect
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(16_000);
    });

    expect(MockEventSource.instances.length).toBe(countAfterRetries);
  });

  it('resets retry count on successful open', () => {
    renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    // one error → retry at 2 s
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(2_000);
    });

    // successful open resets counter
    act(() => {
      latestInstance().triggerOpen();
    });

    // another error should again be 2 s (not 4 s)
    act(() => {
      latestInstance().triggerError();
    });
    act(() => {
      vi.advanceTimersByTime(1_999);
    });
    expect(MockEventSource.instances).toHaveLength(2);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockEventSource.instances).toHaveLength(3);
  });

  /* ------------------------------------------------------------------ */
  /*  Cleanup                                                           */
  /* ------------------------------------------------------------------ */

  it('closes EventSource and clears timer on unmount', () => {
    const closeSpy = vi.spyOn(MockEventSource.prototype, 'close');

    const { unmount } = renderHook(() => useCrawlProgress('job-1'));

    act(() => {
      latestInstance().triggerOpen();
    });

    // trigger an error so a retry timer is pending
    act(() => {
      latestInstance().triggerError();
    });

    unmount();

    expect(closeSpy).toHaveBeenCalled();
  });

  it('cleans up when jobId changes', () => {
    const { rerender } = renderHook(({ id }) => useCrawlProgress(id), {
      initialProps: { id: 'job-1' },
    });

    act(() => {
      latestInstance().triggerOpen();
    });
    const firstEs = latestInstance();

    rerender({ id: 'job-2' });

    expect(firstEs.readyState).toBe(2); // closed
    expect(MockEventSource.instances).toHaveLength(2);

    act(() => {
      latestInstance().triggerOpen();
    });
  });

  it('cleans up when jobId goes to null', () => {
    const { rerender } = renderHook(({ id }) => useCrawlProgress(id), {
      initialProps: { id: 'job-1' },
    });

    act(() => {
      latestInstance().triggerOpen();
    });
    const es = latestInstance();

    rerender({ id: null as unknown as string });

    expect(es.readyState).toBe(2);
  });
});
