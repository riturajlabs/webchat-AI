import { afterEach, describe, expect, it } from 'vitest';
import { autoUpgrade } from './embed';
import { mount } from './mount';

function installCurrentScript(data: Record<string, string>): void {
  const script = document.createElement('script');
  for (const [key, value] of Object.entries(data)) {
    script.dataset[key] = value;
  }
  Object.defineProperty(document, 'currentScript', {
    value: script,
    configurable: true,
  });
}

afterEach(() => {
  Object.defineProperty(document, 'currentScript', {
    value: null,
    configurable: true,
  });
  document.body.innerHTML = '';
});

describe('autoUpgrade', () => {
  it('returns null when the script has no data-widget-id', () => {
    installCurrentScript({});
    expect(autoUpgrade()).toBeNull();
  });

  it('upgrades from data-widget-id and creates a host element', () => {
    installCurrentScript({ widgetId: 'widget_abc' });
    const result = autoUpgrade();
    expect(result?.widgetId).toBe('widget_abc');
    expect(result?.controller).toBeTruthy();
    expect(document.querySelector('webchat-widget')).toBeTruthy();
  });

  it('uses the api-base-url from the script tag', () => {
    installCurrentScript({ widgetId: 'widget_abc', apiBaseUrl: 'https://cdn.example.com/api' });
    const result = autoUpgrade();
    expect(result?.controller?.apiBaseUrl).toBe('https://cdn.example.com/api');
  });
});

describe('mount + embed integration', () => {
  it('mounts into an existing host without a duplicate', () => {
    const host = document.createElement('webchat-widget');
    document.body.appendChild(host);
    const controller = mount({ widgetId: 'widget_1', host });
    expect(controller.widgetId).toBe('widget_1');
    expect(document.querySelectorAll('webchat-widget')).toHaveLength(1);
    controller.destroy();
  });
});
