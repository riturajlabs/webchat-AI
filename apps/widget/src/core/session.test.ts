import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SessionManager, mintSessionToken } from './session';

const API_BASE = 'http://api.example.com/api/widget/v1';
const OPTIONS = { widgetId: 'widget_1', apiBaseUrl: API_BASE };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('mintSessionToken', () => {
  it('POSTs widget_id + visitor_id and returns the token + expiry', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ session_token: 'tok-1', expires_at: '2030-01-01T00:00:00Z' }),
    );
    const result = await mintSessionToken(OPTIONS, 'visitor-1', fetchImpl);
    expect(result.sessionToken).toBe('tok-1');
    expect(fetchImpl).toHaveBeenCalledWith(
      `${API_BASE}/sessions`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ widget_id: 'widget_1', visitor_id: 'visitor-1' }),
      }),
    );
  });

  it('throws a WidgetError with code server on non-OK response', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}, 503));
    await expect(mintSessionToken(OPTIONS, 'visitor-1', fetchImpl)).rejects.toMatchObject({
      code: 'server',
    });
  });
});

describe('SessionManager', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-01-01T00:00:00Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('mints on first ensureFresh and reuses a fresh token', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ session_token: 'tok-1', expires_at: '2025-01-01T00:14:00Z' }),
    );
    const manager = new SessionManager(OPTIONS, 'visitor-1', fetchImpl);
    const first = await manager.ensureFresh();
    expect(first.token).toBe('tok-1');
    expect(fetchImpl).toHaveBeenCalledTimes(1);

    const second = await manager.ensureFresh();
    expect(second.token).toBe('tok-1');
    expect(fetchImpl).toHaveBeenCalledTimes(1); // no re-mint, still fresh
  });

  it('re-mints pre-emptively within 3 minutes of expiry', async () => {
    let call = 0;
    const fetchImpl = vi.fn(async () => {
      call += 1;
      return jsonResponse({
        session_token: `tok-${call}`,
        expires_at: call === 1 ? '2025-01-01T00:12:00Z' : '2025-01-01T00:20:00Z',
      });
    });
    const manager = new SessionManager(OPTIONS, 'visitor-1', fetchImpl);
    const first = await manager.ensureFresh();
    expect(first.token).toBe('tok-1');

    // Advance 2 minutes: only 10 minutes left, still > 3 min margin → reuse.
    vi.advanceTimersByTime(2 * 60 * 1000);
    const second = await manager.ensureFresh();
    expect(second.token).toBe('tok-1');

    // Advance another 2 minutes: only 8 min left → still fresh (margin is 3).
    vi.advanceTimersByTime(2 * 60 * 1000);
    const third = await manager.ensureFresh();
    expect(third.token).toBe('tok-1');

    // Advance to leave only 2 minutes → within margin → re-mint.
    vi.advanceTimersByTime(8 * 60 * 1000);
    const fourth = await manager.ensureFresh();
    expect(fourth.token).toBe('tok-2');
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('reissue always mints a fresh token', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ session_token: 'tok-new', expires_at: '2030-01-01T00:00:00Z' }),
    );
    const manager = new SessionManager(OPTIONS, 'visitor-1', fetchImpl);
    const token = await manager.reissue();
    expect(token.token).toBe('tok-new');
  });
});
