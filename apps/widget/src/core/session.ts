/**
 * Widget session token lifecycle (plan §5, ADR-004).
 *
 * Mints a 15-minute `widget_session_token` via `POST /sessions`, keeps it in
 * memory only (never persisted), and re-mints pre-emptively using the
 * server-provided `expires_at` — not the client clock — for the 12/15-minute
 * renewal margin (plan §9 clock skew).
 */

import { sanitizeApiBaseUrl, type WidgetOptions } from '../config/types';
import { WidgetError } from './errors';
import { fetchWithTimeout } from './network';

/** Session request timeout (plan §9). */
export const SESSION_TIMEOUT_MS = 10 * 1000;

export interface SessionToken {
  token: string;
  expiresAt: number; // epoch ms, from the server's expires_at
}

export interface SessionResult {
  sessionToken: string;
  expiresAt: number;
}

export interface SessionStore {
  get(): SessionToken | null;
  set(token: SessionToken): void;
  clear(): void;
}

/** Pre-emptive renewal: refresh once within 3 minutes of expiry (12/15 min). */
const RENEWAL_MARGIN_MS = 3 * 60 * 1000;

function createMemoryStore(): SessionStore {
  let token: SessionToken | null = null;
  return {
    get() {
      return token;
    },
    set(next: SessionToken) {
      token = next;
    },
    clear() {
      token = null;
    },
  };
}

/** Mint a fresh widget session token from the public API. */
export async function mintSessionToken(
  options: WidgetOptions,
  visitorId: string,
  fetchImpl?: typeof fetch,
): Promise<SessionResult> {
  const apiBaseUrl = sanitizeApiBaseUrl(options.apiBaseUrl ?? '/api/widget/v1');
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${apiBaseUrl}/sessions`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ widget_id: options.widgetId, visitor_id: visitorId }),
      },
      { timeoutMs: SESSION_TIMEOUT_MS, fetchImpl },
    );
  } catch (cause) {
    if (cause instanceof WidgetError) {
      throw cause;
    }
    throw new WidgetError({
      code: cause && (cause as Error).name === 'RequestTimeoutError' ? 'timeout' : 'network',
      message: 'Session request failed',
      cause,
    });
  }
  if (!response.ok) {
    throw new WidgetError({
      code: 'server',
      message: `Session request failed (${response.status})`,
      status: response.status,
    });
  }
  const body = (await response.json()) as { session_token?: string; expires_at?: string };
  if (!body.session_token || !body.expires_at) {
    throw new WidgetError({ code: 'invalid', message: 'Invalid session response' });
  }
  const expiresAt = Date.parse(body.expires_at);
  if (Number.isNaN(expiresAt)) {
    throw new WidgetError({ code: 'invalid', message: 'Invalid session expiry' });
  }
  return { sessionToken: body.session_token, expiresAt };
}

/**
 * Holds the current widget session token and renews it when it nears expiry.
 * `get()` is synchronous (the caller never awaits on the hot path); call
 * `ensureFresh()` before any request that needs a live token.
 */
export class SessionManager {
  private store: SessionStore;
  private readonly fetchImpl: typeof fetch;

  constructor(
    private readonly options: WidgetOptions,
    private readonly visitorId: string,
    fetchImpl?: typeof fetch,
    store?: SessionStore,
  ) {
    this.store = store ?? createMemoryStore();
    this.fetchImpl = fetchImpl ?? fetch;
  }

  get(): SessionToken | null {
    return this.store.get();
  }

  /** True when the held token is valid for at least the renewal margin. */
  isFresh(): boolean {
    const token = this.store.get();
    if (!token) {
      return false;
    }
    return token.expiresAt - Date.now() > RENEWAL_MARGIN_MS;
  }

  /**
   * Return the current token, minting or renewing it when it is missing or
   * within 3 minutes of expiry. Throws WidgetError on network failure.
   */
  async ensureFresh(): Promise<SessionToken> {
    if (this.isFresh()) {
      return this.store.get() as SessionToken;
    }
    const minted = await mintSessionToken(this.options, this.visitorId, this.fetchImpl);
    const token: SessionToken = { token: minted.sessionToken, expiresAt: minted.expiresAt };
    this.store.set(token);
    return token;
  }

  /** Force a re-mint (used after a 401 single retry, plan §9). */
  async reissue(): Promise<SessionToken> {
    const minted = await mintSessionToken(this.options, this.visitorId, this.fetchImpl);
    const token: SessionToken = { token: minted.sessionToken, expiresAt: minted.expiresAt };
    this.store.set(token);
    return token;
  }
}
