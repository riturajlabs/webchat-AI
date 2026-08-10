import { afterEach, describe, expect, it, vi } from 'vitest';
import { RequestTimeoutError, fetchWithTimeout, isOffline } from './network';

describe('fetchWithTimeout', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('forwards the request and returns the response', async () => {
    const fetchImpl = vi.fn(async () => new Response('ok'));
    const response = await fetchWithTimeout(
      'http://x/',
      { method: 'GET' },
      { timeoutMs: 5000, fetchImpl },
    );
    expect(await response.text()).toBe('ok');
    expect(fetchImpl).toHaveBeenCalledWith(
      'http://x/',
      expect.objectContaining({ method: 'GET', signal: expect.any(AbortSignal) }),
    );
  });

  it('aborts and throws RequestTimeoutError when the response exceeds the timeout', async () => {
    vi.useFakeTimers();
    let abortSignal: AbortSignal | undefined;
    const fetchImpl = vi.fn((_url: string | URL | Request, init?: Parameters<typeof fetch>[1]) => {
      abortSignal = init?.signal as AbortSignal;
      return new Promise<Response>((_resolve, reject) => {
        abortSignal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        );
      });
    });

    const promise = fetchWithTimeout('http://x/', undefined, {
      timeoutMs: 1000,
      fetchImpl,
    });
    const assertion = expect(promise).rejects.toBeInstanceOf(RequestTimeoutError);

    vi.advanceTimersByTime(1000);
    await assertion;
  });

  it('does not throw RequestTimeoutError for a manual abort', async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn(
      (_url: string | URL | Request, init?: Parameters<typeof fetch>[1]) =>
        new Promise<Response>((_resolve, reject) => {
          (init?.signal as AbortSignal).addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          );
        }),
    );

    const promise = fetchWithTimeout('http://x/', undefined, {
      timeoutMs: 5000,
      signal: controller.signal,
      fetchImpl,
    });
    const assertion = expect(promise).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await assertion;
  });

  it('clears the internal timer when the request settles early', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => new Response('ok'));
    await fetchWithTimeout('http://x/', undefined, { timeoutMs: 5000, fetchImpl });
    // No pending timers remain after a fast resolution.
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('isOffline', () => {
  const originalOnLine = navigator.onLine;

  afterEach(() => {
    Object.defineProperty(navigator, 'onLine', {
      value: originalOnLine,
      configurable: true,
    });
  });

  it('returns false when the browser is online', () => {
    Object.defineProperty(navigator, 'onLine', { value: true, configurable: true });
    expect(isOffline()).toBe(false);
  });

  it('returns true when the browser reports offline', () => {
    Object.defineProperty(navigator, 'onLine', { value: false, configurable: true });
    expect(isOffline()).toBe(true);
  });
});
