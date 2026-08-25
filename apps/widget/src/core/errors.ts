/**
 * Error taxonomy for the widget SDK (plan §9).
 *
 * Every failure surfaced to the UI maps to one of these stable user-facing
 * codes; raw error text never reaches the user. Backend SSE `error` events
 * carry machine codes (e.g. `WIDGET_DISABLED`) that are mapped here to the
 * stable taxonomy via `errorFromSseCode`.
 */

export type WidgetErrorCode =
  | 'network'
  | 'timeout'
  | 'unauthorized'
  | 'limit'
  | 'server'
  | 'invalid'
  | 'validation'
  | 'ai_unavailable'
  | 'config'
  | 'widget_not_found'
  | 'widget_disabled'
  | 'website_not_ready'
  | 'origin'
  | 'domain_not_configured'
  | 'session';

export interface WidgetErrorOptions {
  code: WidgetErrorCode;
  message: string;
  retryable?: boolean;
  status?: number;
  cause?: unknown;
  /**
   * Backend correlation id for the failed request (Phase 2 tracing): the
   * `X-Request-ID` the widget generated for the turn, echoed by SSE error
   * frames. Null when unknown (e.g. failures before a request was built).
   */
  requestId?: string | null;
}

const USER_FACING_MESSAGES: Record<WidgetErrorCode, string> = {
  network: 'Unable to connect right now. Please try again.',
  timeout: 'The assistant took too long to respond',
  unauthorized: 'Session expired, please retry',
  limit: 'Message limit reached',
  server: 'Sorry, I couldn’t process that. Please try again.',
  invalid: 'That request could not be sent',
  validation: 'Please check your message and try again.',
  ai_unavailable: 'The assistant is temporarily unavailable. Please try again.',
  config: 'Unable to load widget settings',
  widget_not_found: 'Invalid widget ID',
  widget_disabled: 'This assistant is currently unavailable',
  website_not_ready: 'This assistant is still being set up',
  origin: 'This domain is not allowed to embed this assistant',
  domain_not_configured: 'No allowed domains are configured for this assistant',
  session: "Couldn't start the conversation. Please try again.",
};

function isRetryable(code: WidgetErrorCode): boolean {
  switch (code) {
    case 'network':
    case 'timeout':
    case 'unauthorized':
    case 'server':
    case 'ai_unavailable':
    case 'session':
      return true;
    default:
      return false;
  }
}

export class WidgetError extends Error {
  readonly code: WidgetErrorCode;
  readonly status: number | null;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly cause?: unknown;

  constructor(options: WidgetErrorOptions) {
    super(options.message);
    this.name = 'WidgetError';
    this.code = options.code;
    this.status = options.status ?? null;
    this.retryable = options.retryable ?? isRetryable(options.code);
    this.requestId = options.requestId ?? null;
    if (options.cause !== undefined) {
      this.cause = options.cause;
    }
  }

  get userMessage(): string {
    return USER_FACING_MESSAGES[this.code];
  }
}

/** Map an HTTP status to a widget error code (plan §9 error taxonomy). */
export function errorFromStatus(
  status: number,
  message: string,
  requestId?: string | null,
): WidgetError {
  let code: WidgetErrorCode;
  switch (status) {
    case 401:
      code = 'unauthorized';
      break;
    case 429:
      code = 'limit';
      break;
    case 400:
    case 404:
    case 422:
      code = 'invalid';
      break;
    case 503:
      code = 'server';
      break;
    default:
      code = status >= 500 ? 'server' : 'network';
      break;
  }
  return new WidgetError({ code, message, status, requestId: requestId ?? null });
}

/**
 * Backend `AppError` codes mapped onto the stable taxonomy. Used by both the
 * SSE chat error events and the JSON error envelope (`{"error":{"code":...}}`)
 * that the config/session endpoints return. `WIDGET_NOT_FOUND` is surfaced as
 * its own code (the visitor pasted an invalid `data-widget-id`) instead of
 * being folded into `widget_disabled`, so the message is actionable.
 */
const BACKEND_CODE_MAP: Record<string, WidgetErrorCode> = {
  WIDGET_NOT_FOUND: 'widget_not_found',
  WIDGET_DISABLED: 'widget_disabled',
  WEBSITE_NOT_READY: 'website_not_ready',
  MESSAGE_LIMIT_REACHED: 'limit',
  SPAM_REJECTED: 'invalid',
  RATE_LIMIT_EXCEEDED: 'limit',
  INVALID_CREDENTIALS: 'unauthorized',
  INVALID_TOKEN: 'unauthorized',
  TOKEN_EXPIRED: 'unauthorized',
  GENERATION_TIMEOUT: 'timeout',
  GENERATION_FAILED: 'ai_unavailable',
  GENERATION_UNAVAILABLE: 'ai_unavailable',
  AI_UNAVAILABLE: 'ai_unavailable',
  EMBEDDING_FAILED: 'ai_unavailable',
  EMBEDDING_UNAVAILABLE: 'ai_unavailable',
  INVALID_QUESTION: 'validation',
  VALIDATION_ERROR: 'validation',
  WIDGET_ORIGIN_NOT_ALLOWED: 'origin',
  WIDGET_DOMAIN_NOT_CONFIGURED: 'domain_not_configured',
  // Audit S-21: codes emitted by the SSE streaming endpoints that were
  // missing here. Unmapped codes fell back to `server` ("please try
  // again"), which invited futile retries - a plan-cap visitor must hear
  // "limit", and an unknown/expired chat session needs a fresh session,
  // not another identical retry.
  LIMIT_REACHED: 'limit',
  SESSION_NOT_FOUND: 'session',
  SERVICE_UNAVAILABLE: 'ai_unavailable',
  WEBSITE_NOT_FOUND: 'widget_not_found',
};

/**
 * Map a backend error code onto the stable taxonomy.
 * Unknown codes fall back to `server` so internals are never leaked.
 */
export function errorFromBackendCode(
  code: string | undefined,
  message: string,
  status?: number,
  requestId?: string | null,
): WidgetError {
  const mapped = code ? BACKEND_CODE_MAP[code] : undefined;
  return new WidgetError({
    code: mapped ?? 'server',
    message,
    status,
    requestId: requestId ?? null,
  });
}

/**
 * Map a backend SSE `error` event code onto the stable taxonomy.
 * Unknown codes fall back to `server` so internals are never leaked.
 * `requestId` is the correlation id echoed by the backend error frame
 * (Phase 2 tracing) and is surfaced on the resulting {@link WidgetError}.
 */
export function errorFromSseCode(
  code: string | undefined,
  message: string,
  requestId?: string | null,
): WidgetError {
  return errorFromBackendCode(code, message, undefined, requestId);
}

/** Shape of the backend JSON error envelope (`AppError` handler in main.py). */
interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
  };
}

/**
 * Map a non-OK HTTP response's body onto the taxonomy.
 *
 * The backend returns `{"error":{"code":"WIDGET_NOT_FOUND","message":...}}`
 * (see `backend/core/errors.py` + the `AppError` handler). When the body
 * carries that envelope the machine code drives the mapping so the visitor
 * sees a meaningful, actionable message; otherwise it falls back to a
 * status-code guess. Unknown backend codes never leak: they become `server`.
 */
export function errorFromApiBody(
  status: number,
  body: unknown,
  requestId?: string | null,
): WidgetError {
  const envelope = (body ?? {}) as ErrorEnvelope;
  const code = envelope?.error?.code;
  if (code) {
    return errorFromBackendCode(
      code,
      envelope.error?.message ?? `Request failed (${status})`,
      status,
      requestId,
    );
  }
  return errorFromStatus(status, `Request failed (${status})`, requestId);
}
