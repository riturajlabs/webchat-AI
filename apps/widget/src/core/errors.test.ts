import { describe, expect, it } from 'vitest';
import { WidgetError, errorFromApiBody, errorFromSseCode, errorFromStatus } from './errors';

describe('WidgetError', () => {
  it('exposes a stable user-facing message per code', () => {
    expect(new WidgetError({ code: 'network', message: 'x' }).userMessage).toBe(
      'Unable to connect right now. Please try again.',
    );
    expect(new WidgetError({ code: 'widget_disabled', message: 'x' }).userMessage).toBe(
      'This assistant is currently unavailable',
    );
  });

  it('defaults retryability from the code', () => {
    expect(new WidgetError({ code: 'network', message: 'x' }).retryable).toBe(true);
    expect(new WidgetError({ code: 'timeout', message: 'x' }).retryable).toBe(true);
    expect(new WidgetError({ code: 'unauthorized', message: 'x' }).retryable).toBe(true);
    expect(new WidgetError({ code: 'server', message: 'x' }).retryable).toBe(true);
    expect(new WidgetError({ code: 'limit', message: 'x' }).retryable).toBe(false);
    expect(new WidgetError({ code: 'widget_disabled', message: 'x' }).retryable).toBe(false);
    expect(new WidgetError({ code: 'website_not_ready', message: 'x' }).retryable).toBe(false);
  });

  it('lets callers override retryability explicitly', () => {
    expect(new WidgetError({ code: 'limit', message: 'x', retryable: true }).retryable).toBe(true);
  });

  it('keeps the underlying cause for diagnostics', () => {
    const cause = new Error('boom');
    const error = new WidgetError({ code: 'network', message: 'x', cause });
    expect(error.cause).toBe(cause);
  });
});

describe('errorFromStatus', () => {
  it('maps HTTP statuses onto the taxonomy', () => {
    expect(errorFromStatus(401, 'm').code).toBe('unauthorized');
    expect(errorFromStatus(429, 'm').code).toBe('limit');
    expect(errorFromStatus(400, 'm').code).toBe('invalid');
    expect(errorFromStatus(404, 'm').code).toBe('invalid');
    expect(errorFromStatus(503, 'm').code).toBe('server');
    expect(errorFromStatus(500, 'm').code).toBe('server');
    expect(errorFromStatus(302, 'm').code).toBe('network');
  });

  it('preserves the status number on the error', () => {
    expect(errorFromStatus(401, 'm').status).toBe(401);
  });
});

describe('errorFromApiBody', () => {
  it('maps the backend error envelope code onto the taxonomy', () => {
    const error = errorFromApiBody(404, {
      error: { code: 'WIDGET_NOT_FOUND', message: 'Widget not found.' },
    });
    expect(error.code).toBe('widget_not_found');
    expect(error.userMessage).toBe('Invalid widget ID');
    expect(error.status).toBe(404);
  });

  it('maps a disabled widget from the envelope', () => {
    const error = errorFromApiBody(403, {
      error: { code: 'WIDGET_DISABLED', message: 'Widget is not available.' },
    });
    expect(error.code).toBe('widget_disabled');
    expect(error.userMessage).toBe('This assistant is currently unavailable');
    expect(error.retryable).toBe(false);
  });

  it('maps a disallowed embed origin', () => {
    const error = errorFromApiBody(403, {
      error: { code: 'WIDGET_ORIGIN_NOT_ALLOWED', message: 'nope' },
    });
    expect(error.code).toBe('origin');
    expect(error.userMessage).toBe('This domain is not allowed to embed this assistant');
  });

  it('maps an unconfigured domain allowlist', () => {
    const error = errorFromApiBody(403, {
      error: {
        code: 'WIDGET_DOMAIN_NOT_CONFIGURED',
        message: 'No allowed domains are configured for this widget.',
      },
    });
    expect(error.code).toBe('domain_not_configured');
    expect(error.userMessage).toBe('No allowed domains are configured for this assistant');
    expect(error.retryable).toBe(false);
  });

  it('falls back to the status mapping when the body has no envelope', () => {
    expect(errorFromApiBody(503, {}).code).toBe('server');
    expect(errorFromApiBody(429, { message: 'x' }).code).toBe('limit');
    expect(errorFromApiBody(500, 'plain text').code).toBe('server');
    expect(errorFromApiBody(404, {}).code).toBe('invalid');
  });

  it('never leaks unknown backend codes', () => {
    const error = errorFromApiBody(400, {
      error: { code: 'INTERNAL_DB_PASSWORD', message: 'leak' },
    });
    expect(error.code).toBe('server');
    expect(error.userMessage).toBe('Sorry, I couldn’t process that. Please try again.');
  });
});

describe('errorFromSseCode', () => {
  it('maps known backend AppError codes onto the taxonomy', () => {
    expect(errorFromSseCode('WIDGET_NOT_FOUND', 'm').code).toBe('widget_not_found');
    expect(errorFromSseCode('WIDGET_DISABLED', 'm').code).toBe('widget_disabled');
    expect(errorFromSseCode('WEBSITE_NOT_READY', 'm').code).toBe('website_not_ready');
    expect(errorFromSseCode('MESSAGE_LIMIT_REACHED', 'm').code).toBe('limit');
    expect(errorFromSseCode('SPAM_REJECTED', 'm').code).toBe('invalid');
    expect(errorFromSseCode('RATE_LIMIT_EXCEEDED', 'm').code).toBe('limit');
    expect(errorFromSseCode('INVALID_CREDENTIALS', 'm').code).toBe('unauthorized');
    expect(errorFromSseCode('GENERATION_TIMEOUT', 'm').code).toBe('timeout');
    expect(errorFromSseCode('AI_UNAVAILABLE', 'm').code).toBe('ai_unavailable');
    expect(errorFromSseCode('VALIDATION_ERROR', 'm').code).toBe('validation');
    expect(errorFromSseCode('WIDGET_DOMAIN_NOT_CONFIGURED', 'm').code).toBe(
      'domain_not_configured',
    );
  });

  it('provides actionable messages for AI and validation failures', () => {
    expect(errorFromSseCode('GENERATION_UNAVAILABLE', 'internal detail').userMessage).toBe(
      'The assistant is temporarily unavailable. Please try again.',
    );
    expect(errorFromSseCode('INVALID_QUESTION', 'internal detail').userMessage).toBe(
      'Please check your message and try again.',
    );
    expect(errorFromSseCode('GENERATION_UNAVAILABLE', 'internal detail').retryable).toBe(true);
  });

  it('surfaces an invalid widget id with an actionable message', () => {
    const error = errorFromSseCode('WIDGET_NOT_FOUND', 'Widget not found.');
    expect(error.code).toBe('widget_not_found');
    expect(error.userMessage).toBe('Invalid widget ID');
    expect(error.retryable).toBe(false);
  });

  it('falls back to server for unknown codes so internals never leak', () => {
    expect(errorFromSseCode('INTERNAL_DB_PASSWORD', 'm').code).toBe('server');
    expect(errorFromSseCode(undefined, 'm').code).toBe('server');
    expect(errorFromSseCode('', 'm').code).toBe('server');
  });
});
