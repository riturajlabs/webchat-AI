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
}

const USER_FACING_MESSAGES: Record<WidgetErrorCode, string> = {
  network: 'Unable to connect right now. Please try again.',
  timeout: 'The assistant took too long to respond',
  unauthorized: 'Session expired, please retry',
  limit: 'Message limit reached',
  server: 'Sorry, I couldn’t process that. Please try again.',
  invalid: 'That request could not be sent',
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
  readonly cause?: unknown;

  constructor(options: WidgetErrorOptions) {
    super(options.message);
    this.name = 'WidgetError';
    this.code = options.code;
    this.status = options.status ?? null;
    this.retryable = options.retryable ?? isRetryable(options.code);
    if (options.cause !== undefined) {
      this.cause = options.cause;
    }
  }

  get userMessage(): string {
    return USER_FACING_MESSAGES[this.code];
  }
}

/** Map an HTTP status to a widget error code (plan §9 error taxonomy). */
export function errorFromStatus(status: number, message: string): WidgetError {
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
  return new WidgetError({ code, message, status });
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
  WIDGET_ORIGIN_NOT_ALLOWED: 'origin',
  WIDGET_DOMAIN_NOT_CONFIGURED: 'domain_not_configured',
};

/**
 * Map a backend error code onto the stable taxonomy.
 * Unknown codes fall back to `server` so internals are never leaked.
 */
export function errorFromBackendCode(
  code: string | undefined,
  message: string,
  status?: number,
): WidgetError {
  const mapped = code ? BACKEND_CODE_MAP[code] : undefined;
  return new WidgetError({
    code: mapped ?? 'server',
    message,
    status,
  });
}

/**
 * Map a backend SSE `error` event code onto the stable taxonomy.
 * Unknown codes fall back to `server` so internals are never leaked.
 */
export function errorFromSseCode(code: string | undefined, message: string): WidgetError {
  return errorFromBackendCode(code, message);
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
export function errorFromApiBody(status: number, body: unknown): WidgetError {
  const envelope = (body ?? {}) as ErrorEnvelope;
  const code = envelope?.error?.code;
  if (code) {
    return errorFromBackendCode(
      code,
      envelope.error?.message ?? `Request failed (${status})`,
      status,
    );
  }
  return errorFromStatus(status, `Request failed (${status})`);
}
