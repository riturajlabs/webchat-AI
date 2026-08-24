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
import { WidgetError, errorFromApiBody, errorFromSseCode } from '../core/errors';
import { fetchWithTimeout, newRequestId } from '../core/network';
import { readSseStream, type SseEvent } from '../core/sse';
import type { SessionToken } from '../core/session';

/** Connect + first-token timeout for a chat stream (plan §9). */
export const CHAT_CONNECT_TIMEOUT_MS = 30 * 1000;

/**
 * Inactivity watchdog for an established stream (production hardening): when
 * no bytes arrive within this window — stalled server, dead connection without
 * FIN — the reader is cancelled and a retryable `timeout` error ends the turn
 * instead of "AI is typing" forever. Re-armed on every chunk.
 */
export const CHAT_STALL_TIMEOUT_MS = 30 * 1000;

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
  /** Final stream state: "completed" | "failed" (absent on legacy servers). */
  status?: string;
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
  /** Client-side timing measurements for latency analysis. */
  timing?: StreamTiming;
  /**
   * Correlation id sent as `X-Request-ID` for this turn (Phase 2 tracing);
   * also echoed by backend `done`/`error` frames and attached to errors.
   */
  requestId?: string;
}

/** Client-side latency measurements for a chat stream. */
export interface StreamTiming {
  /** Total wall-clock time from request initiation to stream completion (ms). */
  totalMs: number;
  /** Time from request initiation to first delta token (ms). */
  ttftMs: number;
  /** Number of delta events received. */
  deltaCount: number;
}

/** Best-effort parse of a non-OK response body (see `errorFromApiBody`). */
async function readErrorEnvelope(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return {};
  }
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
  const streamStartTime = performance.now();
  // One correlation id per chat turn (Phase 2 tracing): generated once and
  // reused across the 401 re-mint retry so backend logs join the whole turn.
  const requestId = newRequestId();

  let token: SessionToken;
  try {
    token = await client.getToken();
  } catch (cause) {
    const error =
      cause instanceof WidgetError
        ? cause
        : new WidgetError({
            code: 'network',
            message: 'Session unavailable',
            cause,
            requestId,
          });
    handlers.onError?.(error);
    return { completed: false, error, requestId };
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
            'X-Request-ID': requestId,
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
        return { completed: false, aborted: true, requestId };
      }
      const error = new WidgetError({
        code: cause && (cause as Error).name === 'RequestTimeoutError' ? 'timeout' : 'network',
        message: 'Chat request failed',
        cause,
        requestId,
      });
      handlers.onError?.(error);
      return { completed: false, error, requestId };
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
            : new WidgetError({
                code: 'network',
                message: 'Session renewal failed',
                cause,
                requestId,
              });
        handlers.onError?.(error);
        return { completed: false, error, requestId };
      }
    }

    if (!response.ok) {
      // The backend answers auth failures (e.g. a foreign-origin embed) with
      // the JSON error envelope; parse it so the visitor gets a meaningful
      // message rather than a generic status guess.
      const body = await readErrorEnvelope(response);
      const error = errorFromApiBody(response.status, body, requestId);
      handlers.onError?.(error);
      return { completed: false, error, requestId };
    }

    if (!response.body) {
      const error = new WidgetError({
        code: 'invalid',
        message: 'Chat stream missing body',
        requestId,
      });
      handlers.onError?.(error);
      return { completed: false, error, requestId };
    }

    try {
      return await consumeStream(response.body, handlers, signal, streamStartTime, {
        stallTimeoutMs: CHAT_STALL_TIMEOUT_MS,
        requestId,
      });
    } catch (cause) {
      if (signal?.aborted) {
        return { completed: false, aborted: true, requestId };
      }
      throw cause;
    }
  }
}

/** Options for {@link consumeStream} beyond the raw stream body. */
interface ConsumeOptions {
  stallTimeoutMs?: number;
  /** Correlation id for this turn (Phase 2 tracing), attached to errors. */
  requestId?: string;
}

/**
 * Consume the SSE body, dispatching events. `done`/`error` are honored exactly
 * once; anything after the terminal event is ignored.
 */
async function consumeStream(
  body: ReadableStream<Uint8Array>,
  handlers: ChatHandlers,
  signal?: AbortSignal,
  streamStartTime?: number,
  options: ConsumeOptions = {},
): Promise<StreamResult> {
  const { stallTimeoutMs = CHAT_STALL_TIMEOUT_MS, requestId } = options;
  let terminalReached = false;
  let result: StreamResult = { completed: false, ...(requestId ? { requestId } : {}) };
  let firstTokenTime: number | null = null;
  let deltaCount = 0;

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
              if (firstTokenTime === null) {
                firstTokenTime = performance.now();
              }
              deltaCount += 1;
              handlers.onDelta?.(delta);
            }
            break;
          }
          case 'done': {
            terminalReached = true;
            const payload = (event.data ?? {}) as DonePayload;
            // Terminal-state protocol: the server always closes with `done`
            // carrying a final `status`. A failed status maps onto the same
            // error path as a bare `error` frame; anything else - including
            // servers that predate the `status` field - is a success, and the
            // terminal-idempotency guard above keeps exactly one outcome.
            if (payload.status === 'failed') {
              const code = typeof payload.code === 'string' ? payload.code : undefined;
              const message = typeof payload.message === 'string' ? payload.message : 'Chat failed';
              const error = errorFromSseCode(
                code,
                message,
                typeof payload.request_id === 'string' ? payload.request_id : requestId,
              );
              result = { completed: false, error, ...(requestId ? { requestId } : {}) };
              handlers.onError?.(error);
              break;
            }
            result = { completed: true, done: payload, ...(requestId ? { requestId } : {}) };
            handlers.onDone?.(payload);
            break;
          }
          case 'error': {
            terminalReached = true;
            const payload = (event.data ?? {}) as {
              code?: string;
              message?: string;
              request_id?: string;
            };
            const error = errorFromSseCode(
              payload.code,
              payload.message ?? 'Chat failed',
              typeof payload.request_id === 'string' ? payload.request_id : requestId,
            );
            result = { completed: false, error, ...(requestId ? { requestId } : {}) };
            handlers.onError?.(error);
            break;
          }
          default:
            break;
        }
      },
      signal,
      stallTimeoutMs,
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
      requestId: requestId ?? null,
    });
    result = { completed: false, error, ...(requestId ? { requestId } : {}) };
    handlers.onError?.(error);
  }
  if (streamStartTime !== undefined) {
    const now = performance.now();
    result.timing = {
      totalMs: Math.round(now - streamStartTime),
      ttftMs: firstTokenTime !== null ? Math.round(firstTokenTime - streamStartTime) : 0,
      deltaCount,
    };
  }
  return result;
}
