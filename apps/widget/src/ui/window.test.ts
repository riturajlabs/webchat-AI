import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createChatWindow } from './window';
import { defaultConfig, type WidgetPublicConfig } from '../config/types';

function setup(configOverrides: Partial<WidgetPublicConfig> = {}) {
  const config = { ...defaultConfig('widget_1'), ...configOverrides };
  const onSend = vi.fn();
  const onClose = vi.fn();
  const onSuggested = vi.fn();
  const onRetry = vi.fn();
  const onDismiss = vi.fn();
  const messagesElement = document.createElement('div');
  messagesElement.className = 'wc-messages';
  const windowApi = createChatWindow({
    config,
    messagesElement,
    onSend,
    onClose,
    onSuggested,
    onRetry,
    onDismiss,
    isDisabled: () => false,
  });
  document.body.appendChild(windowApi.element);
  return { windowApi, onSend, onClose, onSuggested, onRetry, onDismiss, config, messagesElement };
}

function pressKey(target: EventTarget, key: string, options: { shift?: boolean } = {}): void {
  target.dispatchEvent(
    new KeyboardEvent('keydown', {
      key,
      bubbles: true,
      cancelable: true,
      shiftKey: Boolean(options.shift),
    }),
  );
}

describe('createChatWindow', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('exposes a modal dialog with labelled landmark semantics', () => {
    const { windowApi } = setup();
    expect(windowApi.element.getAttribute('role')).toBe('dialog');
    expect(windowApi.element.getAttribute('aria-modal')).toBe('true');
    expect(windowApi.element.getAttribute('aria-labelledby')).toBeTruthy();
    expect(windowApi.element.querySelector('.wc-close')?.getAttribute('aria-label')).toBe(
      'Close chat window',
    );
    expect(windowApi.element.querySelector('.wc-status-live')?.getAttribute('aria-live')).toBe(
      'polite',
    );
    expect(windowApi.element.querySelector('.wc-banner')?.getAttribute('role')).toBe('alert');
  });

  it('closes on Escape', () => {
    const { windowApi, onClose } = setup();
    windowApi.trapFocus();
    pressKey(windowApi.composer.input, 'Escape');
    expect(onClose).toHaveBeenCalledTimes(1);
    windowApi.releaseFocus();
  });

  it('trapFocus moves focus into the composer', () => {
    const { windowApi } = setup();
    windowApi.trapFocus();
    expect(document.activeElement).toBe(windowApi.composer.input);
    windowApi.releaseFocus();
  });

  it('wraps Tab focus within the window', () => {
    const { windowApi } = setup();
    windowApi.trapFocus();
    const close = windowApi.element.querySelector<HTMLButtonElement>(
      '.wc-close',
    ) as HTMLButtonElement;
    const textarea = windowApi.composer.input;

    // Tab on the last enabled focusable (composer) wraps to the first (close).
    textarea.focus();
    pressKey(textarea, 'Tab');
    expect(document.activeElement).toBe(close);

    // Shift+Tab on the first wraps to the last.
    close.focus();
    pressKey(close, 'Tab', { shift: true });
    expect(document.activeElement).toBe(textarea);
    windowApi.releaseFocus();
  });

  it('pulls focus into the window when Tab lands outside it', () => {
    const { windowApi } = setup();
    windowApi.trapFocus();
    const close = windowApi.element.querySelector<HTMLButtonElement>(
      '.wc-close',
    ) as HTMLButtonElement;
    document.body.focus();
    pressKey(document.body, 'Tab');
    expect(document.activeElement).toBe(close);
    windowApi.releaseFocus();
  });

  it('keeps links in the Tab cycle instead of trapping on them', () => {
    const { windowApi, messagesElement } = setup();
    // Assistant markdown/citation links are natively tabbable; the focus trap
    // must treat them as focusables (WCAG 2.1.2 — no keyboard trap).
    const link = document.createElement('a');
    link.href = 'https://example.com/docs';
    link.textContent = 'Docs';
    messagesElement.appendChild(link);
    windowApi.trapFocus();

    link.focus();
    pressKey(link, 'Tab');
    expect(document.activeElement).not.toBe(windowApi.element.querySelector('.wc-close'));
    expect(windowApi.element.contains(document.activeElement)).toBe(true);

    // Shift+Tab from the link cycles back inside the window too.
    pressKey(link, 'Tab', { shift: true });
    expect(windowApi.element.contains(document.activeElement)).toBe(true);
    windowApi.releaseFocus();
  });

  it('releaseFocus stops intercepting Tab', () => {
    const { windowApi } = setup();
    const outside = document.createElement('button');
    document.body.appendChild(outside);
    windowApi.trapFocus();
    windowApi.releaseFocus();
    outside.focus();
    pressKey(outside, 'Tab');
    expect(document.activeElement).toBe(outside);
  });

  it('sets and clears the banner', () => {
    const { windowApi } = setup();
    windowApi.setBanner("Can't reach the assistant");
    expect(windowApi.currentBanner()).toBe("Can't reach the assistant");
    windowApi.setBanner(null);
    expect(windowApi.currentBanner()).toBe('');
  });

  it('shows Retry only for retryable banners and wires actions', () => {
    const { windowApi, onRetry, onDismiss } = setup();

    windowApi.setBanner('Something went wrong', true);
    expect(windowApi.currentBanner()).toBe('Something went wrong');
    const retry = windowApi.element.querySelector<HTMLButtonElement>('.wc-banner-retry');
    const dismiss = windowApi.element.querySelector<HTMLButtonElement>('.wc-banner-dismiss');
    expect(retry?.hidden).toBe(false);
    expect(dismiss?.hidden).toBe(false);

    retry?.click();
    expect(onRetry).toHaveBeenCalledTimes(1);
    dismiss?.click();
    expect(onDismiss).toHaveBeenCalledTimes(1);

    // Non-retryable banners hide the Retry action.
    windowApi.setBanner('Limit reached');
    expect(retry?.hidden).toBe(true);
    expect(dismiss?.hidden).toBe(false);
  });

  it('syncSuggested swaps the suggested-questions row', () => {
    const { windowApi, onSuggested } = setup();
    windowApi.syncSuggested(['What is pricing?']);
    const chips = windowApi.element.querySelectorAll('.wc-chip');
    expect(chips.length).toBe(1);
    expect(chips[0].textContent).toBe('What is pricing?');
    (chips[0] as HTMLButtonElement).click();
    expect(onSuggested).toHaveBeenCalledWith('What is pricing?');
  });

  it('sends via the composer with the configured placeholder', () => {
    const { windowApi, onSend } = setup();
    windowApi.composer.input.value = 'hello';
    windowApi.composer.input.dispatchEvent(new Event('input'));
    windowApi.composer.sendButton.click();
    expect(onSend).toHaveBeenCalledWith('hello');
  });

  it('setStreaming reflects on the composer Stop button', () => {
    const { windowApi } = setup();
    windowApi.setStreaming(true);
    expect(windowApi.composer.stopButton.hidden).toBe(false);
    expect(windowApi.composer.sendButton.hidden).toBe(true);
    windowApi.setStreaming(false);
    expect(windowApi.composer.stopButton.hidden).toBe(true);
    expect(windowApi.composer.sendButton.hidden).toBe(false);
  });

  it('setStatus drives the visually-hidden live region', () => {
    const { windowApi } = setup();
    const status = windowApi.element.querySelector<HTMLElement>('.wc-status-live');
    windowApi.setStatus('Code copied');
    expect(status?.textContent).toBe('Code copied');
    windowApi.setStatus('');
    expect(status?.textContent).toBe('');
  });

  it('renders the dynamic header branding and a brand footer by default', () => {
    const { windowApi, config } = setup();
    const heading = windowApi.element.querySelector<HTMLElement>('.wc-window-brand');
    expect(heading?.textContent).toBe(config.bot_name);
    const statusText = windowApi.element.querySelector<HTMLElement>('.wc-status-text');
    expect(statusText?.textContent).toBe(config.bot_status_text);
    const footer = windowApi.element.querySelector<HTMLElement>('.wc-window-footer');
    expect(footer).toBeTruthy();
    expect(footer?.hidden).toBe(false);
    expect(footer?.textContent).toContain('Powered by WebChat AI');
  });

  it('hides the brand footer when branding is disabled', () => {
    const windowApi = createChatWindow({
      config: { ...defaultConfig('widget_1'), branding: false },
      messagesElement: document.createElement('div'),
      onSend: () => {},
      onClose: () => {},
      onSuggested: () => {},
      onRetry: () => {},
      onDismiss: () => {},
      isDisabled: () => false,
    });
    document.body.appendChild(windowApi.element);
    const footer = windowApi.element.querySelector<HTMLElement>('.wc-window-footer');
    expect(footer?.hidden).toBe(true);
  });

  it('uses the avatar (falling back to logo) for the header brand icon', () => {
    const windowApi = createChatWindow({
      config: {
        ...defaultConfig('widget_1'),
        avatar_url: 'https://example.com/avatar.png',
        logo_url: 'https://example.com/logo.png',
      },
      messagesElement: document.createElement('div'),
      onSend: () => {},
      onClose: () => {},
      onSuggested: () => {},
      onRetry: () => {},
      onDismiss: () => {},
      isDisabled: () => false,
    });
    document.body.appendChild(windowApi.element);
    const img = windowApi.element.querySelector<HTMLImageElement>('.wc-brand-logo');
    expect(img?.src).toContain('avatar.png');
  });

  it('syncConfig re-brands the header, composer placeholder and footer', () => {
    const { windowApi } = setup();
    windowApi.syncConfig({
      ...defaultConfig('widget_1'),
      bot_name: 'Acme Support',
      bot_status_text: 'Away',
      placeholder: 'Ask Acme…',
      branding: false,
      avatar_url: 'https://example.com/acme.png',
    });
    const heading = windowApi.element.querySelector<HTMLElement>('.wc-window-brand');
    expect(heading?.textContent).toBe('Acme Support');
    const statusText = windowApi.element.querySelector<HTMLElement>('.wc-status-text');
    expect(statusText?.textContent).toBe('Away');
    expect(windowApi.composer.input.placeholder).toBe('Ask Acme…');
    const footer = windowApi.element.querySelector<HTMLElement>('.wc-window-footer');
    expect(footer?.hidden).toBe(true);
    const img = windowApi.element.querySelector<HTMLImageElement>('.wc-brand-logo');
    expect(img?.src).toContain('acme.png');
  });
});

describe('Escape scoping (audit W-05)', () => {
  it('closes when Escape is pressed inside the window', () => {
    const { windowApi, onClose } = setup();
    windowApi.trapFocus();
    pressKey(windowApi.composer.input, 'Escape');
    expect(onClose).toHaveBeenCalledTimes(1);
    windowApi.releaseFocus();
  });

  it('ignores Escape pressed on the host page so its shortcuts keep working', () => {
    const { windowApi, onClose, messagesElement } = setup();
    document.body.appendChild(messagesElement);
    windowApi.trapFocus();

    // Focus lives outside the widget (e.g. a host lightbox): the global
    // capture listener must neither close nor swallow the event.
    const outside = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    const prevented = vi.spyOn(outside, 'preventDefault');
    document.body.dispatchEvent(outside);
    expect(onClose).not.toHaveBeenCalled();
    expect(prevented).not.toHaveBeenCalled();
    windowApi.releaseFocus();
  });

  it('still closes via the composed path when focus sits in a nested element', () => {
    const { windowApi, onClose } = setup();
    windowApi.trapFocus();
    const close = windowApi.element.querySelector<HTMLButtonElement>('.wc-close')!;
    pressKey(close, 'Escape');
    expect(onClose).toHaveBeenCalledTimes(1);
    windowApi.releaseFocus();
  });
});

describe('brand image URL safety (audit W-22)', () => {
  it('renders http(s) brand images', () => {
    const { windowApi } = setup({ avatar_url: 'https://cdn.example.com/bot.png' });
    const logo = windowApi.element.querySelector<HTMLImageElement>('.wc-brand-logo');
    expect(logo?.src).toBe('https://cdn.example.com/bot.png');
  });

  it('falls back to the glyph for unsafe image schemes', () => {
    for (const url of [
      'javascript:alert(1)',
      'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=',
      '//evil.example/track.png',
      'blob:https://example.com/x',
    ]) {
      const { windowApi } = setup({ avatar_url: url });
      expect(windowApi.element.querySelector('img')).toBeNull();
      expect(windowApi.element.querySelector('.wc-brand-icon svg')).toBeTruthy();
    }
  });
});
