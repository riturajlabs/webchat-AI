import { afterEach, describe, expect, it, vi } from 'vitest';
import { profileTurn } from './mount';

describe('profileTurn', () => {
  const originalDebug = console.debug;

  afterEach(() => {
    console.debug = originalDebug;
    vi.restoreAllMocks();
  });

  it('logs time-to-first-token exactly once', () => {
    const debug = vi.fn();
    console.debug = debug;
    const profiler = profileTurn('widget_1');
    profiler.markFirstToken();
    profiler.markFirstToken();
    expect(debug).toHaveBeenCalledTimes(1);
    expect(String(debug.mock.calls[0][0])).toMatch(/\[webchat:widget_1\] first token in \d+ms/);
  });

  it('logs the turn duration and includes backend total when provided', () => {
    const debug = vi.fn();
    console.debug = debug;
    const profiler = profileTurn('widget_1');
    profiler.complete({ embedding_ms: 10, retrieval_ms: 25, generation_ms: 140, total_ms: 175 });
    const message = String(debug.mock.calls[0][0]);
    expect(message).toMatch(/\[webchat:widget_1\] turn complete in \d+ms/);
    expect(message).toContain('backend total 175ms');
    expect(message).toContain('embedding 10ms');
    expect(message).toContain('retrieval 25ms');
    expect(message).toContain('generation 140ms');
  });

  it('omits the backend phases when no timing data is available', () => {
    const debug = vi.fn();
    console.debug = debug;
    const profiler = profileTurn('widget_1');
    profiler.complete();
    const message = String(debug.mock.calls[0][0]);
    expect(message).not.toContain('backend total');
    expect(message).not.toContain('embedding');
  });
});
