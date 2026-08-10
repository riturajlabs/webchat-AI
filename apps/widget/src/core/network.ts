/**
 * Offline + timeout helpers (plan §9).
 *
 * `fetchWithTimeout` bounds every request (config 5 s, chat connect 10 s,
 * first token 20 s). `isOffline` checks `navigator.onLine`, defaulting to
 * online when the API is unavailable.
 */

export interface TimeoutOptions {
  /** Abort after this many milliseconds. */
  timeoutMs: number;
  /** Optional external signal to also honour. */
  signal?: AbortSignal;
}

export class RequestTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`Request timed out after ${timeoutMs}ms`);
    this.name = 'RequestTimeoutError';
  }
}

/** fetch() that aborts after `timeoutMs`. */
export async function fetchWithTimeout(
  input: string | URL | Request,
  init: RequestInit | undefined,
  { timeoutMs, signal, fetchImpl }: TimeoutOptions & { fetchImpl?: typeof fetch },
): Promise<Response> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const onExternalAbort = (): void => controller.abort();
  signal?.addEventListener('abort', onExternalAbort, { once: true });

  const doFetch = fetchImpl ?? fetch;
  try {
    return await doFetch(input, { ...init, signal: controller.signal });
  } catch (cause) {
    if (timedOut) {
      throw new RequestTimeoutError(timeoutMs);
    }
    throw cause;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onExternalAbort);
  }
}

/** Report whether the browser currently believes it is offline. */
export function isOffline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false;
}
