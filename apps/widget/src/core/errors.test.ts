import { describe, expect, it } from 'vitest';
import { WidgetError, errorFromSseCode, errorFromStatus } from './errors';

describe('WidgetError', () => {
  it('exposes a stable user-facing message per code', () => {
    expect(new WidgetError({ code: 'network', message: 'x' }).userMessage).toBe(
      "Can't reach the assistant",
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

describe('errorFromSseCode', () => {
  it('maps known backend AppError codes onto the taxonomy', () => {
    expect(errorFromSseCode('WIDGET_NOT_FOUND', 'm').code).toBe('widget_disabled');
    expect(errorFromSseCode('WIDGET_DISABLED', 'm').code).toBe('widget_disabled');
    expect(errorFromSseCode('WEBSITE_NOT_READY', 'm').code).toBe('website_not_ready');
    expect(errorFromSseCode('MESSAGE_LIMIT_REACHED', 'm').code).toBe('limit');
    expect(errorFromSseCode('SPAM_REJECTED', 'm').code).toBe('invalid');
    expect(errorFromSseCode('RATE_LIMIT_EXCEEDED', 'm').code).toBe('limit');
  });

  it('falls back to server for unknown codes so internals never leak', () => {
    expect(errorFromSseCode('INTERNAL_DB_PASSWORD', 'm').code).toBe('server');
    expect(errorFromSseCode(undefined, 'm').code).toBe('server');
    expect(errorFromSseCode('', 'm').code).toBe('server');
  });
});
