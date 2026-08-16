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
  it('returns an empty result when there is nothing to upgrade', () => {
    installCurrentScript({});
    expect(autoUpgrade()).toEqual([]);
  });

  it('upgrades from data-widget-id and creates a host element', () => {
    installCurrentScript({ widgetId: 'widget_abc' });
    const result = autoUpgrade();
    expect(result).toHaveLength(1);
    expect(result[0].widgetId).toBe('widget_abc');
    expect(result[0].controller).toBeTruthy();
    expect(document.querySelector('webchat-widget')).toBeTruthy();
  });

  it('resolves a host-only api-base-url from the script tag', () => {
    installCurrentScript({ widgetId: 'widget_abc', apiBaseUrl: 'https://cdn.example.com' });
    const result = autoUpgrade();
    expect(result[0].controller?.apiBaseUrl).toBe('https://cdn.example.com/api/widget/v1');
  });

  it('keeps an already-versioned api-base-url unchanged', () => {
    installCurrentScript({
      widgetId: 'widget_abc',
      apiBaseUrl: 'https://cdn.example.com/api/widget/v1',
    });
    const result = autoUpgrade();
    expect(result[0].controller?.apiBaseUrl).toBe('https://cdn.example.com/api/widget/v1');
  });

  it('falls back to the same-origin base when data-api-base-url is empty', () => {
    installCurrentScript({ widgetId: 'widget_abc', apiBaseUrl: '' });
    const result = autoUpgrade();
    expect(result[0].controller?.apiBaseUrl).toBe('/api/widget/v1');
  });

  it('mounts every host independently with its own widget id and session', () => {
    installCurrentScript({});
    const host1 = document.createElement('webchat-widget');
    host1.setAttribute('data-widget-id', 'widget_abc');
    host1.setAttribute('data-api-base-url', 'https://a.example.com');
    const host2 = document.createElement('webchat-widget');
    host2.setAttribute('data-widget-id', 'widget_xyz');
    host2.setAttribute('data-api-base-url', 'https://b.example.com');
    document.body.appendChild(host1);
    document.body.appendChild(host2);

    const result = autoUpgrade();

    expect(result).toHaveLength(2);
    expect(result[0].widgetId).toBe('widget_abc');
    expect(result[0].controller?.apiBaseUrl).toBe('https://a.example.com/api/widget/v1');
    expect(result[1].widgetId).toBe('widget_xyz');
    expect(result[1].controller?.apiBaseUrl).toBe('https://b.example.com/api/widget/v1');
    expect(result[0].controller?.session).not.toBe(result[1].controller?.session);
    result[0].controller?.destroy();
    result[1].controller?.destroy();
  });

  it('falls back to the script tag widget id for hosts without their own', () => {
    installCurrentScript({ widgetId: 'widget_script' });
    const host1 = document.createElement('webchat-widget');
    const host2 = document.createElement('webchat-widget');
    host2.setAttribute('data-widget-id', 'widget_own');
    document.body.appendChild(host1);
    document.body.appendChild(host2);

    const result = autoUpgrade();

    expect(result).toHaveLength(2);
    expect(result[0].widgetId).toBe('widget_script');
    expect(result[1].widgetId).toBe('widget_own');
    result[0].controller?.destroy();
    result[1].controller?.destroy();
  });

  it('keeps mounting the remaining hosts when one host fails', () => {
    installCurrentScript({});
    // A host that already hosts a closed shadow tree cannot be re-mounted;
    // `attachShadow` throws and must not block the other host.
    const host1 = document.createElement('webchat-widget');
    host1.setAttribute('data-widget-id', 'widget_abc');
    host1.attachShadow({ mode: 'closed' });
    const host2 = document.createElement('webchat-widget');
    host2.setAttribute('data-widget-id', 'widget_xyz');
    host2.attachShadow({ mode: 'open' });
    document.body.appendChild(host1);
    document.body.appendChild(host2);

    const result = autoUpgrade();

    expect(result).toHaveLength(1);
    expect(result[0].widgetId).toBe('widget_xyz');
    expect(host2.shadowRoot?.querySelector('.wc-shell')).toBeTruthy();
    result[0].controller?.destroy();
  });

  it('does not duplicate the UI when the same host is upgraded twice', () => {
    installCurrentScript({ widgetId: 'widget_abc' });
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    document.body.appendChild(host);

    autoUpgrade();
    const second = autoUpgrade();

    expect(second).toHaveLength(1);
    expect(second[0].widgetId).toBe('widget_abc');
    expect(host.shadowRoot?.querySelectorAll('.wc-shell')).toHaveLength(1);
    second[0].controller?.destroy();
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
