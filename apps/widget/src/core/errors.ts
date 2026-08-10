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
  | 'widget_disabled'
  | 'website_not_ready';

export interface WidgetErrorOptions {
  code: WidgetErrorCode;
  message: string;
  retryable?: boolean;
  status?: number;
  cause?: unknown;
}

const USER_FACING_MESSAGES: Record<WidgetErrorCode, string> = {
  network: "Can't reach the assistant",
  timeout: 'The assistant took too long to respond',
  unauthorized: 'Session expired, please retry',
  limit: 'Message limit reached',
  server: 'Something went wrong on our side',
  invalid: 'That request could not be sent',
  config: 'Unable to load widget settings',
  widget_disabled: 'This assistant is currently unavailable',
  website_not_ready: 'This assistant is still being set up',
};

function isRetryable(code: WidgetErrorCode): boolean {
  switch (code) {
    case 'network':
    case 'timeout':
    case 'unauthorized':
    case 'server':
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

/** Backend AppError codes the widget chat route can emit as SSE error events. */
const SSE_CODE_MAP: Record<string, WidgetErrorCode> = {
  WIDGET_NOT_FOUND: 'widget_disabled',
  WIDGET_DISABLED: 'widget_disabled',
  WEBSITE_NOT_READY: 'website_not_ready',
  MESSAGE_LIMIT_REACHED: 'limit',
  SPAM_REJECTED: 'invalid',
  RATE_LIMIT_EXCEEDED: 'limit',
};

/**
 * Map a backend SSE `error` event code onto the stable taxonomy.
 * Unknown codes fall back to `server` so internals are never leaked.
 */
export function errorFromSseCode(code: string | undefined, message: string): WidgetError {
  const mapped = code ? SSE_CODE_MAP[code] : undefined;
  return new WidgetError({
    code: mapped ?? 'server',
    message,
  });
}
