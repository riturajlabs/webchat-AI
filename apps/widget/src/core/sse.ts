/**
 * Server-Sent-Events parsing for POST streams (plan §5.1).
 *
 * `EventSource` only does GET; the chat endpoint is POST, so we read the
 * response body with `fetch` + `ReadableStream` and parse the SSE wire format
 * (`event:` / `data:` lines, events separated by a blank line). Handles
 * multi-line data, partial frames split across chunks, and buffers unfinished
 * events until the stream closes.
 */

import { WidgetError } from './errors';

export interface SseEvent {
  event: string;
  data: unknown;
}

const DATA_MULTILINE_JOINER = '\n';

/**
 * Parse one complete SSE frame (already split on a blank line) into an event.
 * `data:` fields are JSON-decoded when possible; otherwise kept as the raw text.
 */
export function parseSseFrame(frame: string): SseEvent {
  let eventName = 'message';
  const dataLines: string[] = [];

  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (line.startsWith(':')) {
      continue; // comment line
    }
    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
    }
    // Unknown fields (`id`, `retry`, …) are ignored.
  }

  const rawData = dataLines.join(DATA_MULTILINE_JOINER);
  let data: unknown = rawData;
  if (rawData) {
    try {
      data = JSON.parse(rawData);
    } catch {
      // Not JSON — keep the raw text.
    }
  }
  return { event: eventName, data };
}

/**
 * Read an SSE response body, invoking `onEvent` for each complete frame.
 * The stream is consumed until the reader signals done or `signal` aborts.
 * On abort the underlying reader is cancelled so a stalled connection can't
 * leave the Stop-generation button hanging (Phase 10).
 */
export async function readSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const cancel = (): void => {
    reader.cancel().catch(() => undefined);
  };
  const onAbort = (): void => cancel();
  signal?.addEventListener('abort', onAbort, { once: true });
  if (signal?.aborted) {
    cancel();
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (signal?.aborted) {
        throw new WidgetError({ code: 'timeout', message: 'Stream aborted' });
      }
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (frame.trim()) {
          onEvent(parseSseFrame(frame));
        }
        boundary = buffer.indexOf('\n\n');
      }
    }
    if (buffer.trim()) {
      onEvent(parseSseFrame(buffer));
    }
  } catch (cause) {
    // A cancelled reader rejects with an AbortError; surface it as the
    // recognisable WidgetError so callers map it to `{ aborted: true }`.
    if (signal?.aborted) {
      throw new WidgetError({ code: 'timeout', message: 'Stream aborted' });
    }
    throw cause;
  } finally {
    signal?.removeEventListener('abort', onAbort);
    // cancel() releases the lock; releaseLock() then throws — ignore it.
    try {
      reader.releaseLock();
    } catch {
      // already released via cancel()
    }
  }
}
