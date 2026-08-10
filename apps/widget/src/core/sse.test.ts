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
});
