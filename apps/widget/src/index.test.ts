import { describe, expect, it } from 'vitest';
import { init } from './index';

describe('init', () => {
  it('mounts the widget without throwing', () => {
    expect(() => init({ widgetId: 'widget_123' })).not.toThrow();
  });

  it('returns a controller exposing the widget id', () => {
    const controller = init({ widgetId: 'widget_123' });
    expect(controller.widgetId).toBe('widget_123');
    controller.destroy();
  });
});
