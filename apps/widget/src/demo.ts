/**
 * Demo page for the WebChat AI widget (dev only — `vite dev`).
 *
 * `?embedded=1` renders just the widget (used by the mobile-preview iframe).
 * Otherwise a control panel lets you pick a widget ID / API base, theme colors
 * (host CSS variables), toggle dark mode and drive open/close through the real
 * SDK controller.
 */

import { mount } from './index';
import type { WidgetController } from './core/mount';

const params = new URLSearchParams(window.location.search);
const embedded = params.get('embedded') === '1';

const HOST_TAG = 'webchat-widget';

function createHost(): HTMLElement {
  const host = document.createElement(HOST_TAG);
  document.body.appendChild(host);
  return host;
}

function mountWidget(
  widgetId: string,
  apiBaseUrl?: string,
): { controller: WidgetController; host: HTMLElement } {
  const host = createHost();
  const controller = mount({ widgetId, apiBaseUrl, host });
  void controller.ready().then(() => applyThemeVars());
  return { controller, host };
}

// --- Theme (host CSS variables) --------------------------------------------

const DARK_VARS: Record<string, string> = {
  '--wc-surface': '#111827',
  '--wc-surface-elevated': '#1f2937',
  '--wc-text': '#f9fafb',
  '--wc-muted': '#9ca3af',
  '--wc-border': '#374151',
  '--wc-bubble-bg': '#1f2937',
};

const LIGHT_VARS = Object.keys(DARK_VARS);

let activeHost: HTMLElement | null = null;
let darkMode = false;
let primaryColor = '#10A37F';
let accentColor = '#25D366';

function applyThemeVars(): void {
  if (!activeHost) {
    return;
  }
  activeHost.style.setProperty('--wc-primary', primaryColor);
  activeHost.style.setProperty('--wc-accent', accentColor);
  for (const name of LIGHT_VARS) {
    if (darkMode) {
      activeHost.style.setProperty(name, DARK_VARS[name]);
    } else {
      activeHost.style.removeProperty(name);
    }
  }
}

// --- Controls ---------------------------------------------------------------

function wireControls(): void {
  const widgetInput = document.getElementById('widget-id') as HTMLInputElement;
  const apiInput = document.getElementById('api-base') as HTMLInputElement;

  document.getElementById('mount')?.addEventListener('click', () => {
    mountDemo();
  });

  document.getElementById('destroy')?.addEventListener('click', () => {
    destroyDemo();
  });

  document.getElementById('open')?.addEventListener('click', () => {
    controller?.open();
  });

  document.getElementById('close')?.addEventListener('click', () => {
    controller?.close();
  });

  document.getElementById('toggle-dark')?.addEventListener('click', () => {
    darkMode = !darkMode;
    document.body.classList.toggle('dark', darkMode);
    applyThemeVars();
  });

  const swatches = document.querySelectorAll<HTMLButtonElement>('.swatch');
  swatches.forEach((swatch) => {
    swatch.addEventListener('click', () => {
      primaryColor = swatch.dataset.primary ?? primaryColor;
      accentColor = swatch.dataset.accent ?? accentColor;
      swatches.forEach((s) => s.classList.toggle('active', s === swatch));
      applyThemeVars();
    });
  });

  document
    .getElementById('preview')
    ?.setAttribute(
      'src',
      `?embedded=1&widget=${encodeURIComponent(widgetInput.value || 'demo')}&api=${encodeURIComponent(apiInput.value || '')}`,
    );
}

let controller: WidgetController | null = null;

function mountDemo(): void {
  destroyDemo();
  const widgetId =
    (document.getElementById('widget-id') as HTMLInputElement).value.trim() || 'demo';
  const apiBase = (document.getElementById('api-base') as HTMLInputElement).value.trim();
  ({ controller, host: activeHost } = mountWidget(widgetId, apiBase || undefined));
  document
    .getElementById('preview')
    ?.setAttribute(
      'src',
      `?embedded=1&widget=${encodeURIComponent(widgetId)}&api=${encodeURIComponent(apiBase)}`,
    );
  document.querySelector('.stage-note')?.remove();
}

function destroyDemo(): void {
  controller?.destroy();
  controller = null;
  activeHost = null;
  document.querySelectorAll(HOST_TAG).forEach((el) => el.remove());
}

// --- Boot -------------------------------------------------------------------

if (embedded) {
  const widgetId = params.get('widget') || 'demo';
  const api = params.get('api') || '';
  mountWidget(widgetId, api || undefined);
} else {
  wireControls();
  mountDemo();
}
