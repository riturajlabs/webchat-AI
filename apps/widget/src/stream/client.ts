/**
 * Chat stream client (plan §5, ADR-004).
 *
 * `POST /api/widget/v1/chat` with `Authorization: Bearer <widget_session_token>`.
 * Parses the SSE stream and dispatches `sources` / `message` / `done` / `error`
 * events. Handles the 401 single-retry (re-mint via /sessions, then retry the
 * in-flight request exactly once — plan §9), and enforces `done`/`error`
 * terminal-event idempotency.
 */

import { resolveApiBaseUrl, type WidgetOptions } from '../config/types';
import { WidgetError, errorFromSseCode, errorFromStatus } from '../core/errors';
import { fetchWithTimeout } from '../core/network';
import { readSseStream, type SseEvent } from '../core/sse';
import type { SessionToken } from '../core/session';

/** Connect + first-token timeout for a chat stream (plan §9). */
export const CHAT_CONNECT_TIMEOUT_MS = 20 * 1000;

export interface ChatRequest {
  question: string;
  sessionId?: string | null;
}

export interface ChatSource {
  chunk_id?: string;
  url?: string;
  title?: string;
  score?: number;
  citation?: string;
}

export interface DonePayload {
  session_id?: string;
  message_id?: string;
  [key: string]: unknown;
}

export interface ChatHandlers {
  onSources?: (sources: ChatSource[]) => void;
  onDelta?: (delta: string) => void;
  onDone?: (done: DonePayload) => void;
  onError?: (error: WidgetError) => void;
}

export interface ChatClientOptions {
  /** Callback that returns a fresh (or re-minted) session token. */
  getToken: () => Promise<SessionToken>;
  /** Force a token re-mint, used once on 401. */
  reissueToken: () => Promise<SessionToken>;
}

export interface StreamResult {
  /** True when the stream ended with a terminal `done` event. */
  completed: boolean;
  /** True when the stream was cancelled by the user (Stop button). */
  aborted?: boolean;
  done?: DonePayload;
  error?: WidgetError;
}

/**
 * Send a chat message and consume the SSE stream to `handlers`.
 * Returns a `StreamResult` describing how the stream ended.
 *
 * `signal` (Phase 10) cancels the in-flight request/stream — used by the Stop
 * button. An abort surfaces as `{ aborted: true }` with no error handlers, so
 * the caller can keep the partial answer without showing an error.
 */
export async function streamChat(
  options: WidgetOptions,
  request: ChatRequest,
  handlers: ChatHandlers,
  client: ChatClientOptions,
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<StreamResult> {
  const apiBaseUrl = resolveApiBaseUrl(options.apiBaseUrl);

  let token: SessionToken;
  try {
    token = await client.getToken();
  } catch (cause) {
    const error =
      cause instanceof WidgetError
        ? cause
        : new WidgetError({ code: 'network', message: 'Session unavailable', cause });
    handlers.onError?.(error);
    return { completed: false, error };
  }

  for (let attempt = 0; ; attempt += 1) {
    let response: Response;
    try {
      response = await fetchWithTimeout(
        `${apiBaseUrl}/chat`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token.token}`,
            Accept: 'text/event-stream',
          },
          body: JSON.stringify({
            question: request.question,
            session_id: request.sessionId ?? null,
          }),
        },
        { timeoutMs: CHAT_CONNECT_TIMEOUT_MS, fetchImpl, signal },
      );
    } catch (cause) {
      if (signal?.aborted) {
        return { completed: false, aborted: true };
      }
      const error = new WidgetError({
        code: cause && (cause as Error).name === 'RequestTimeoutError' ? 'timeout' : 'network',
        message: 'Chat request failed',
        cause,
      });
      handlers.onError?.(error);
      return { completed: false, error };
    }

    if (response.status === 401 && attempt === 0) {
      // Single-retry: re-mint the session token and retry the request once.
      try {
        token = await client.reissueToken();
        continue;
      } catch (cause) {
        const error =
          cause instanceof WidgetError
            ? cause
            : new WidgetError({ code: 'network', message: 'Session renewal failed', cause });
        handlers.onError?.(error);
        return { completed: false, error };
      }
    }

    if (!response.ok) {
      const error = errorFromStatus(response.status, `Chat request failed (${response.status})`);
      handlers.onError?.(error);
      return { completed: false, error };
    }

    if (!response.body) {
      const error = new WidgetError({ code: 'invalid', message: 'Chat stream missing body' });
      handlers.onError?.(error);
      return { completed: false, error };
    }

    try {
      return await consumeStream(response.body, handlers, signal);
    } catch (cause) {
      if (signal?.aborted) {
        return { completed: false, aborted: true };
      }
      throw cause;
    }
  }
}

/**
 * Consume the SSE body, dispatching events. `done`/`error` are honored exactly
 * once; anything after the terminal event is ignored.
 */
async function consumeStream(
  body: ReadableStream<Uint8Array>,
  handlers: ChatHandlers,
  signal?: AbortSignal,
): Promise<StreamResult> {
  let terminalReached = false;
  let result: StreamResult = { completed: false };

  try {
    await readSseStream(
      body,
      (event: SseEvent) => {
        if (terminalReached) {
          return; // terminal-event idempotency guard
        }
        switch (event.event) {
          case 'sources':
            handlers.onSources?.((event.data as { sources?: ChatSource[] }).sources ?? []);
            break;
          case 'message': {
            const delta = (event.data as { delta?: string }).delta;
            if (typeof delta === 'string') {
              handlers.onDelta?.(delta);
            }
            break;
          }
          case 'done': {
            terminalReached = true;
            const done = (event.data ?? {}) as DonePayload;
            result = { completed: true, done };
            handlers.onDone?.(done);
            break;
          }
          case 'error': {
            terminalReached = true;
            const payload = (event.data ?? {}) as { code?: string; message?: string };
            const error = errorFromSseCode(payload.code, payload.message ?? 'Chat failed');
            result = { completed: false, error };
            handlers.onError?.(error);
            break;
          }
          default:
            break;
        }
      },
      signal,
    );
  } catch (cause) {
    // The SSE reader raises a WidgetError when `signal` aborts (sse.ts).
    if (signal?.aborted) {
      return { completed: false, aborted: true };
    }
    throw cause;
  }

  if (!terminalReached && !result.error) {
    // Stream ended without a terminal event — the connection dropped mid-turn,
    // so the unanswered question is retryable (plan §9).
    const error = new WidgetError({
      code: 'network',
      message: 'Chat stream ended unexpectedly',
    });
    result = { completed: false, error };
    handlers.onError?.(error);
  }
  return result;
}
