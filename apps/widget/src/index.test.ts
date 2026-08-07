import { describe, expect, it, vi } from 'vitest';
import { init } from './index';

describe('init', () => {
  it('mounts the widget without throwing', () => {
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined);
    expect(() => init({ widgetId: 'widget_123' })).not.toThrow();
    info.mockRestore();
  });
});
