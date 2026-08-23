import { describe, expect, it } from 'vitest';
import { parseSseFrame, readSseStream } from './sse';

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

describe('parseSseFrame', () => {
  it('parses a single event:data frame', () => {
    expect(parseSseFrame('event: message\ndata: {"delta":"hi"}')).toEqual({
      event: 'message',
      data: { delta: 'hi' },
    });
  });

  it('joins multi-line data into a single field (SSE spec)', () => {
    expect(parseSseFrame('event: message\ndata: line one\ndata: line two')).toEqual({
      event: 'message',
      data: 'line one\nline two',
    });
  });

  it('defaults the event name to message', () => {
    expect(parseSseFrame('data: {"done":true}')).toEqual({
      event: 'message',
      data: { done: true },
    });
  });

  it('keeps non-JSON data as the raw string', () => {
    expect(parseSseFrame('data: hello world')).toEqual({ event: 'message', data: 'hello world' });
  });
});

describe('readSseStream', () => {
  it('parses events split across chunks and emits each complete frame', async () => {
    const events: unknown[] = [];
    await readSseStream(streamFrom(['event: mess', 'age\ndata: {"d', 'elta":"hi"}\n\n']), (e) =>
      events.push(e),
    );
    expect(events).toEqual([{ event: 'message', data: { delta: 'hi' } }]);
  });

  it('parses a single chunk containing multiple complete events', async () => {
    const events: unknown[] = [];
    await readSseStream(
      streamFrom([
        'event: sources\ndata: {"sources":[{"url":"a"}]}\n\nevent: done\ndata: {"message_id":"m"}\n\n',
      ]),
      (e) => events.push(e),
    );
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: 'sources', data: { sources: [{ url: 'a' }] } });
    expect(events[1]).toEqual({ event: 'done', data: { message_id: 'm' } });
  });

  it('buffers partial events until the stream closes', async () => {
    const events: unknown[] = [];
    await readSseStream(streamFrom(['event: done\ndata: {"message_id":"m"}\n']), (e) =>
      events.push(e),
    );
    expect(events).toEqual([{ event: 'done', data: { message_id: 'm' } }]);
  });

  it('throws a WidgetError when the signal aborts a stalled stream', async () => {
    const controller = new AbortController();
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(encoder.encode('event: message\ndata: {"delta":"x"}\n\n'));
      },
    });
    const events: unknown[] = [];
    const promise = readSseStream(body, (e) => events.push(e), controller.signal);
    controller.abort();
    await expect(promise).rejects.toMatchObject({ code: 'timeout' });
  });
});

describe('readSseStream stall watchdog', () => {
  /** A stream that emits one frame and then hangs (server stall, no FIN). */
  function stalledStream(firstChunk: string): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    return new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(firstChunk));
      },
    });
  }

  /** A stream that dribbles chunks with delays, then closes (slow but alive). */
  function delayedStream(chunks: string[], delayMs: number): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    return new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((chunk, index) => {
          setTimeout(
            () => {
              try {
                controller.enqueue(encoder.encode(chunk));
              } catch {
                // Stream was cancelled before this chunk fired.
              }
              if (index === chunks.length - 1) {
                controller.close();
              }
            },
            delayMs * (index + 1),
          );
        });
      },
    });
  }

  it('raises a retryable timeout when no bytes arrive within stallTimeoutMs', async () => {
    const events: unknown[] = [];
    await expect(
      readSseStream(
        stalledStream('event: message\ndata: {"delta":"Hel"}\n\n'),
        (e) => events.push(e),
        undefined,
        25,
      ),
    ).rejects.toMatchObject({ code: 'timeout', retryable: true, message: 'Stream stalled' });
    // Events delivered before the stall are not lost.
    expect(events).toHaveLength(1);
  });

  it('re-arms the watchdog per chunk so slow-but-alive streams complete', async () => {
    const events: { event: string }[] = [];
    await readSseStream(
      delayedStream(
        [
          'event: message\ndata: {"delta":"a"}\n\n',
          'event: message\ndata: {"delta":"b"}\n\n',
          'event: done\ndata: {}\n\n',
        ],
        15,
      ),
      (e) => events.push(e),
      undefined,
      60,
    );
    expect(events.map((e) => e.event)).toEqual(['message', 'message', 'done']);
  });

  it('without a stallTimeoutMs even slow streams are never cut off', async () => {
    // Gaps far longer than any watchdog used elsewhere in this suite; with no
    // stallTimeoutMs there is no deadline, so the stream completes.
    const events: { event: string }[] = [];
    await readSseStream(
      delayedStream(['event: message\ndata: {"delta":"a"}\n\n', 'event: done\ndata: {}\n\n'], 120),
      (e) => events.push(e),
    );
    expect(events.map((e) => e.event)).toEqual(['message', 'done']);
  });

  it('parses CRLF-terminated frames (proxy line endings)', async () => {
    const chunks = [
      'event: message\r\ndata: {"delta":"hi"}\r\n\r\n',
      'event: done\r\ndata: {}\r\n\r\n',
    ];
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    });
    const events: { event: string }[] = [];
    await readSseStream(body, (e) => events.push(e));
    expect(events.map((e) => e.event)).toEqual(['message', 'done']);
  });

  it('abort still wins over the stall watchdog', async () => {
    const controller = new AbortController();
    const promise = readSseStream(
      stalledStream('event: message\ndata: {"delta":"x"}\n\n'),
      () => {},
      controller.signal,
      20,
    );
    controller.abort();
    await expect(promise).rejects.toMatchObject({ message: 'Stream aborted' });
  });
});
