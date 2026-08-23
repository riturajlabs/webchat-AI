import { afterEach, describe, expect, it, vi } from 'vitest';
import { CHAT_CONNECT_TIMEOUT_MS, CHAT_STALL_TIMEOUT_MS, streamChat } from './client';
import type { SessionToken } from '../core/session';

const API_BASE = 'http://api.example.com/api/widget/v1';
const OPTIONS = { widgetId: 'widget_1', apiBaseUrl: API_BASE };

function sseResponse(events: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const event of events) {
        controller.enqueue(encoder.encode(event));
      }
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

function sessionToken(token: string): SessionToken {
  return { token, expiresAt: Date.now() + 15 * 60 * 1000 };
}

function handlers() {
  return {
    onSources: vi.fn(),
    onDelta: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
  };
}

describe('streamChat', () => {
  it('streams sources, deltas and done', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: sources\ndata: {"sources":[{"url":"a"}]}\n\n',
        'event: message\ndata: {"delta":"Hel"}\n\n',
        'event: message\ndata: {"delta":"lo"}\n\n',
        'event: done\ndata: {"session_id":"s1","message_id":"m1"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(true);
    expect(result.done?.session_id).toBe('s1');
    expect(h.onSources).toHaveBeenCalledWith([{ url: 'a' }]);
    expect(h.onDelta).toHaveBeenCalledWith('Hel');
    expect(h.onDelta).toHaveBeenCalledWith('lo');
    expect(h.onDone).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
  });

  it('sends the Bearer token and body', async () => {
    const fetchImpl = vi.fn(async () => sseResponse([]));
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    await streamChat(OPTIONS, { question: 'hi there', sessionId: 's-9' }, h, client, fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith(
      `${API_BASE}/chat`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer tok-1',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ question: 'hi there', session_id: 's-9' }),
      }),
    );
  });

  it('re-mints the token and retries exactly once on a 401', async () => {
    let call = 0;
    const fetchImpl = vi.fn(async () => {
      call += 1;
      if (call === 1) {
        return new Response('unauthorized', { status: 401 });
      }
      return sseResponse(['event: done\ndata: {"session_id":"s2"}\n\n']);
    });
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(true);
    expect(client.reissueToken).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('does not retry a 401 a second time', async () => {
    const fetchImpl = vi.fn(async () => new Response('unauthorized', { status: 401 }));
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(false);
    expect(client.reissueToken).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(h.onError).toHaveBeenCalled();
  });

  it('surfaces error events from the stream', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse(['event: error\ndata: {"code":"SPAM_REJECTED","message":"Rejected"}\n\n']),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(false);
    expect(result.error?.code).toBe('invalid');
    expect(h.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'invalid' }));
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it('treats a legacy done event without status as success (backward compatible)', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse(['event: done\ndata: {"session_id":"s1","message_id":"m1"}\n\n']),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(true);
    expect(result.done?.session_id).toBe('s1');
    expect(h.onDone).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
  });

  it('completes successfully on done with status completed', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: message\ndata: {"delta":"Hi"}\n\n',
        'event: done\ndata: {"status":"completed","session_id":"s1"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(true);
    expect(result.error).toBeUndefined();
    expect(h.onDone).toHaveBeenCalledTimes(1);
    expect(h.onDone.mock.calls[0][0].status).toBe('completed');
    expect(h.onError).not.toHaveBeenCalled();
  });

  it('reports failure exactly once when error is followed by the failed terminal done', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: message\ndata: {"delta":"par"}\n\n',
        'event: error\ndata: {"code":"GENERATION_FAILED","message":"provider down"}\n\n',
        'event: done\ndata: {"status":"failed","code":"GENERATION_FAILED","message":"provider down"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);

    expect(result.completed).toBe(false);
    expect(result.error?.code).toBe('ai_unavailable');
    // One failure transition only: the trailing failed done must not
    // produce a duplicate onError (no double error banner in the UI).
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it('maps a standalone failed-status done onto the error path', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: message\ndata: {"delta":"par"}\n\n',
        'event: done\ndata: {"status":"failed","code":"MESSAGE_LIMIT_REACHED","message":"cap hit"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);

    expect(result.completed).toBe(false);
    expect(result.error?.code).toBe('limit');
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it('maps AI availability SSE errors to a retryable user-facing error', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: error\ndata: {"code":"GENERATION_UNAVAILABLE","message":"provider failed"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);

    expect(result.error?.code).toBe('ai_unavailable');
    expect(result.error?.userMessage).toBe(
      'The assistant is temporarily unavailable. Please try again.',
    );
    expect(result.error?.retryable).toBe(true);
    expect(h.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'ai_unavailable' }));
  });

  it('maps backend widget errors to the stable taxonomy, never leaking internals', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse(['event: error\ndata: {"code":"WIDGET_DISABLED","message":"disabled"}\n\n']),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.error?.code).toBe('widget_disabled');
    expect(result.error?.retryable).toBe(false);

    const fetchUnknown = vi.fn(async () =>
      sseResponse(['event: error\ndata: {"code":"SUPER_SECRET","message":"leak"}\n\n']),
    );
    const resultUnknown = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchUnknown);
    expect(resultUnknown.error?.code).toBe('server');
    expect(resultUnknown.error?.userMessage).toBe(
      'Sorry, I couldn’t process that. Please try again.',
    );
  });

  it('marks a stream that ends without a terminal event as a retryable network drop', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(['event: message\ndata: {"delta":"par"}\n\n']));
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(false);
    expect(result.error?.code).toBe('network');
    expect(result.error?.retryable).toBe(true);
    expect(h.onError).toHaveBeenCalledTimes(1);
  });

  it('honors done only once (terminal idempotency)', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: done\ndata: {"session_id":"s1"}\n\n',
        'event: done\ndata: {"session_id":"s2"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(h.onDone).toHaveBeenCalledTimes(1);
  });

  it('maps non-OK responses through the error taxonomy', async () => {
    const fetchImpl = vi.fn(async () => new Response('limit', { status: 429 }));
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.error?.code).toBe('limit');
  });

  it('reads the backend error envelope on non-OK responses', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { code: 'WIDGET_DISABLED', message: 'off' } }), {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.error?.code).toBe('widget_disabled');
    expect(result.error?.userMessage).toBe('This assistant is currently unavailable');
    expect(h.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'widget_disabled' }));
  });

  it('classifies a slow connect as a timeout error', async () => {
    vi.useFakeTimers();
    let abortSignal: AbortSignal | undefined;
    const fetchImpl = vi.fn(
      (_url: string | URL | Request, init?: Parameters<typeof fetch>[1]) =>
        new Promise<Response>((_resolve, reject) => {
          abortSignal = init?.signal as AbortSignal;
          abortSignal?.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          );
        }),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const resultPromise = streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    await vi.advanceTimersByTimeAsync(CHAT_CONNECT_TIMEOUT_MS);
    const result = await resultPromise;
    expect(result.completed).toBe(false);
    expect(result.error?.code).toBe('timeout');
    expect(h.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'timeout' }));
  });

  it('cancels a stalled stream and returns aborted (Stop button)', async () => {
    const controller = new AbortController();
    const encoder = new TextEncoder();
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start(c) {
              c.enqueue(encoder.encode('event: message\ndata: {"delta":"par"}\n\n'));
            },
          }),
          { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
        ),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const resultPromise = streamChat(
      OPTIONS,
      { question: 'hi' },
      h,
      client,
      fetchImpl,
      controller.signal,
    );
    controller.abort();
    const result = await resultPromise;
    expect(result.completed).toBe(false);
    expect(result.aborted).toBe(true);
    expect(result.error).toBeUndefined();
    expect(h.onError).not.toHaveBeenCalled();
  });

  it('ends a turn with a retryable timeout when an established stream stalls', async () => {
    vi.useFakeTimers();
    const encoder = new TextEncoder();
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start(c) {
              c.enqueue(encoder.encode('event: message\ndata: {"delta":"par"}\n\n'));
              // No further chunks and no FIN: a dead/stalled connection.
            },
          }),
          { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
        ),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const resultPromise = streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    // Attach the rejection handler before the watchdog fires so the rejection
    // is never unhandled while fake timers advance.
    const stallAssertion = expect(resultPromise).rejects.toMatchObject({
      code: 'timeout',
      retryable: true,
      message: 'Stream stalled',
    });
    await vi.advanceTimersByTimeAsync(CHAT_STALL_TIMEOUT_MS);
    await stallAssertion;
    // The partial delta delivered before the stall is not lost.
    expect(h.onDelta).toHaveBeenCalledWith('par');
  });

  it('includes timing measurements in StreamResult', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: sources\ndata: {"sources":[]}\n\n',
        'event: message\ndata: {"delta":"Hel"}\n\n',
        'event: message\ndata: {"delta":"lo"}\n\n',
        'event: done\ndata: {"session_id":"s1"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(true);
    expect(result.timing).toBeDefined();
    expect(result.timing!.totalMs).toBeGreaterThanOrEqual(0);
    expect(result.timing!.ttftMs).toBeGreaterThanOrEqual(0);
    expect(result.timing!.deltaCount).toBe(2);
  });

  it('reports zero ttftMs when no deltas received', async () => {
    const fetchImpl = vi.fn(async () =>
      sseResponse([
        'event: sources\ndata: {"sources":[]}\n\n',
        'event: done\ndata: {"session_id":"s1"}\n\n',
      ]),
    );
    const h = handlers();
    const client = {
      getToken: vi.fn(async () => sessionToken('tok-1')),
      reissueToken: vi.fn(async () => sessionToken('tok-2')),
    };
    const result = await streamChat(OPTIONS, { question: 'hi' }, h, client, fetchImpl);
    expect(result.completed).toBe(true);
    expect(result.timing).toBeDefined();
    expect(result.timing!.ttftMs).toBe(0);
    expect(result.timing!.deltaCount).toBe(0);
  });
});

afterEach(() => {
  vi.useRealTimers();
});
