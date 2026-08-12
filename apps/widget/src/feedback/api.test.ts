import { describe, expect, it, vi } from 'vitest';
import { submitFeedback } from './api';
import type { SessionToken } from '../core/session';

const API_BASE = 'http://api.example.com/api/widget/v1';
const OPTIONS = { widgetId: 'widget_1', apiBaseUrl: API_BASE };

function sessionToken(token: string): SessionToken {
  return { token, expiresAt: Date.now() + 15 * 60 * 1000 };
}

function client() {
  return {
    getToken: vi.fn(async () => sessionToken('tok-1')),
    reissueToken: vi.fn(async () => sessionToken('tok-2')),
  };
}

const PAYLOAD = {
  sessionId: 's-1',
  messageId: 'm-1',
  rating: 5 as const,
  category: 'helpful' as const,
  comment: 'Great answer',
};

describe('submitFeedback', () => {
  it('posts the rating to /feedback with the Bearer token', async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 }));
    const c = client();
    await submitFeedback(OPTIONS, PAYLOAD, c, fetchImpl);

    expect(fetchImpl).toHaveBeenCalledWith(
      `${API_BASE}/feedback`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer tok-1',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({
          session_id: 's-1',
          message_id: 'm-1',
          rating: 5,
          category: 'helpful',
          comment: 'Great answer',
        }),
      }),
    );
    expect(c.getToken).toHaveBeenCalledTimes(1);
  });

  it('resolves on a 204 (no body)', async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 }));
    await expect(submitFeedback(OPTIONS, PAYLOAD, client(), fetchImpl)).resolves.toBeUndefined();
  });

  it('re-mints the token and retries exactly once on a 401', async () => {
    let call = 0;
    const fetchImpl = vi.fn(async () => {
      call += 1;
      if (call === 1) {
        return new Response('unauthorized', { status: 401 });
      }
      return new Response(null, { status: 204 });
    });
    const c = client();
    await submitFeedback(OPTIONS, PAYLOAD, c, fetchImpl);

    expect(c.reissueToken).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('throws a limit error on 429', async () => {
    const fetchImpl = vi.fn(async () => new Response('rate limited', { status: 429 }));
    await expect(submitFeedback(OPTIONS, PAYLOAD, client(), fetchImpl)).rejects.toMatchObject({
      code: 'limit',
    });
  });

  it('throws an invalid error on 404 (message not found)', async () => {
    const fetchImpl = vi.fn(async () => new Response('missing', { status: 404 }));
    await expect(submitFeedback(OPTIONS, PAYLOAD, client(), fetchImpl)).rejects.toMatchObject({
      code: 'invalid',
    });
  });

  it('throws a network error when the fetch fails', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('fetch failed');
    });
    await expect(submitFeedback(OPTIONS, PAYLOAD, client(), fetchImpl)).rejects.toMatchObject({
      code: 'network',
    });
  });

  it('throws a timeout error when the request times out', async () => {
    const fetchImpl = vi.fn(async () => {
      const error = new Error('aborted');
      error.name = 'RequestTimeoutError';
      throw error;
    });
    await expect(submitFeedback(OPTIONS, PAYLOAD, client(), fetchImpl)).rejects.toMatchObject({
      code: 'timeout',
    });
  });

  it('does not retry a second 401', async () => {
    const fetchImpl = vi.fn(async () => new Response('unauthorized', { status: 401 }));
    const c = client();
    await expect(submitFeedback(OPTIONS, PAYLOAD, c, fetchImpl)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    expect(c.reissueToken).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
