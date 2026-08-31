/**
 * Feedback submission client (Phase 12.4, ADR-005 §5.6).
 *
 * `POST /api/widget/v1/feedback` with `Authorization: Bearer <widget_session_token>`.
 * The visitor's rating (1-5) + category + optional comment is validated and
 * deduped server-side; a repeat rating for the same message is idempotent.
 * Mirrors the chat client's error handling: a single 401 re-mints the token
 * and retries exactly once, and every failure maps onto the stable
 * `WidgetError` taxonomy.
 */

import { resolveApiBaseUrl, type WidgetOptions } from '../config/types';
import { WidgetError, errorFromStatus } from '../core/errors';
import { fetchWithTimeout } from '../core/network';
import type { SessionToken } from '../core/session';

/** Feedback request timeout (plan §9). */
export const FEEDBACK_TIMEOUT_MS = 10 * 1000;

/** Feedback categories the backend accepts (ADR-005 §5.6). */
export type FeedbackCategory = 'helpful' | 'wrong' | 'incomplete' | 'offensive' | 'other';

export interface FeedbackPayload {
  sessionId: string;
  messageId: string;
  /** 1-5 star scale (the control maps 4-5 → helpful, 3 → other, 1-2 → wrong). */
  rating: 1 | 2 | 3 | 4 | 5;
  category: FeedbackCategory;
  comment: string;
}

export interface FeedbackClientOptions {
  /** Callback that returns a fresh (or re-minted) session token. */
  getToken: () => Promise<SessionToken>;
  /** Force a token re-mint, used once on 401. */
  reissueToken: () => Promise<SessionToken>;
}

/**
 * Submit a visitor rating. Resolves when the backend acknowledged the rating
 * (HTTP 204); throws a `WidgetError` on any failure. Idempotent server-side,
 * so a retry after a network blip cannot create a duplicate.
 */
export async function submitFeedback(
  options: WidgetOptions,
  payload: FeedbackPayload,
  client: FeedbackClientOptions,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl(options.apiBaseUrl);

  let token: SessionToken;
  try {
    token = await client.getToken();
  } catch (cause) {
    throw new WidgetError({
      code: cause instanceof WidgetError ? cause.code : 'network',
      message: 'Session unavailable',
      cause,
    });
  }

  for (let attempt = 0; ; attempt += 1) {
    let response: Response;
    try {
      response = await fetchWithTimeout(
        `${apiBaseUrl}/feedback`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token.token}`,
          },
          body: JSON.stringify({
            session_id: payload.sessionId,
            message_id: payload.messageId,
            rating: payload.rating,
            category: payload.category,
            comment: payload.comment,
          }),
        },
        { timeoutMs: FEEDBACK_TIMEOUT_MS, fetchImpl },
      );
    } catch (cause) {
      throw new WidgetError({
        code: cause && (cause as Error).name === 'RequestTimeoutError' ? 'timeout' : 'network',
        message: 'Feedback request failed',
        cause,
      });
    }

    if (response.status === 401 && attempt === 0) {
      // Single-retry: re-mint the session token and retry the request once.
      try {
        token = await client.reissueToken();
        continue;
      } catch (cause) {
        throw new WidgetError({
          code: cause instanceof WidgetError ? cause.code : 'network',
          message: 'Session renewal failed',
          cause,
        });
      }
    }

    if (!response.ok) {
      throw errorFromStatus(response.status, `Feedback request failed (${response.status})`);
    }
    return;
  }
}
