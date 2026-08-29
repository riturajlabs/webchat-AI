import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from './mount';

beforeEach(() => {
  // Force the reduced-motion path so close() hides synchronously instead of
  // waiting out the 180ms close animation.
  window.matchMedia = vi.fn().mockReturnValue({ matches: true });
});

describe('mount', () => {
  it('returns a controller bound to the given widget id', () => {
    const controller = mount({ widgetId: 'widget_123' });
    expect(controller.widgetId).toBe('widget_123');
    expect(controller.apiBaseUrl).toBe('/api/widget/v1');
    expect(controller.visitorId).toBeTruthy();
    controller.destroy();
  });

  it('resolves a host-only api base url to the versioned path', () => {
    const controller = mount({
      widgetId: 'widget_123',
      apiBaseUrl: 'https://api.example.com',
    });
    expect(controller.apiBaseUrl).toBe('https://api.example.com/api/widget/v1');
    controller.destroy();
  });

  it('attaches a closed shadow root to the host element', () => {
    const host = document.createElement('webchat-widget');
    document.body.appendChild(host);
    mount({ widgetId: 'widget_123', host });
    expect(host.shadowRoot).toBeNull(); // closed mode: not reachable from outside
    host.remove();
  });

  it('open/close toggles the chat window state', () => {
    const controller = mount({ widgetId: 'widget_123' });
    expect(controller.isOpen()).toBe(false);
    controller.open();
    expect(controller.isOpen()).toBe(true);
    controller.close();
    expect(controller.isOpen()).toBe(false);
    controller.destroy();
  });

  it('returns the existing controller when the host is already mounted', () => {
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    document.body.appendChild(host);

    const first = mount({ widgetId: 'widget_1', host });
    const again = mount({ widgetId: 'widget_1', host });

    expect(again).toBe(first);
    expect(host.shadowRoot?.querySelectorAll('.wc-shell')).toHaveLength(1);

    again.destroy();
    expect(document.querySelector('webchat-widget')).toBeNull();
  });

  it('removes event listeners on destroy (Phase 12)', () => {
    const controller = mount({ widgetId: 'widget_123' });

    const removeSpy = vi.spyOn(EventTarget.prototype, 'removeEventListener');

    controller.destroy();

    expect(removeSpy).toHaveBeenCalled();

    removeSpy.mockRestore();
  });

  it('supports multiple mount/destroy cycles without leaked listeners', () => {
    // Mount, destroy, then mount again: no errors and no leaked state.
    const c1 = mount({ widgetId: 'cycle_1' });
    c1.destroy();

    const c2 = mount({ widgetId: 'cycle_2' });
    expect(c2.widgetId).toBe('cycle_2');
    expect(c2.isOpen()).toBe(false);
    c2.destroy();
  });
});
