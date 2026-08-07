import { describe, expect, it, vi } from 'vitest';
import { mount } from './mount';

describe('mount', () => {
  it('returns a context bound to the given widget id', () => {
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined);
    const context = mount({ widgetId: 'widget_123' });
    expect(context.widgetId).toBe('widget_123');
    expect(context.apiBaseUrl).toBe('/api/widget/v1');
    expect(info).toHaveBeenCalledTimes(1);
    info.mockRestore();
  });

  it('honours an explicit api base url', () => {
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined);
    const context = mount({ widgetId: 'widget_123', apiBaseUrl: 'https://api.example.com' });
    expect(context.apiBaseUrl).toBe('https://api.example.com');
    info.mockRestore();
  });
});
