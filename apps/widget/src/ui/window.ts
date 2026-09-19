/**
 * Chat window shell (plan §5, WCAG 2.2 AA).
 *
 * A `role="dialog"` + `aria-modal="true"` + `aria-labelledby` window with a
 * header (title/branding/close), a message list region, a suggested-questions
 * row and a composer footer. Streaming/status live regions announce updates.
 *
 * Keyboard (plan §8): `Esc` closes; while open, focus is trapped inside the
 * window (Tab/Shift+Tab cycle composer ↔ send ↔ chips ↔ close) and the first
 * focusable receives focus. Focus is released and returned to the launcher on
 * close (wired in `mount.ts`).
 *
 * Phase 10: `setStreaming` swaps the composer Send ↔ Stop controls while a
 * turn streams, and `setStatus` drives the visually-hidden `wc-status-live`
 * region for "typing / responding" announcements.
 */

import type { WidgetPublicConfig } from '../config/types';
import { renderBrandLogo } from './branding';
import { createComposer } from './composer';
import type { ChatComposer } from './composer';
import { closeIcon, footerLogo } from './icons';
import { createSuggested } from './suggested';

/**
 * Content of the error/notice banner. `title` is a short concise heading,
 * `message` the human-readable explanation. Retry is only offered when the
 * failure is retryable; a safe backend correlation id may be shown subtly.
 */
export interface BannerContent {
  title: string;
  message: string;
  retryable: boolean;
  requestId?: string | null;
}

export interface ChatWindowOptions {
  config: WidgetPublicConfig;
  messagesElement: HTMLElement;
  onSend: (question: string) => void;
  onClose: () => void;
  onSuggested: (question: string) => void;
  /** Re-send the last failed question (plan §9 retry action). */
  onRetry: () => void;
  /** Dismiss the banner (plan §9). Also fired by the 15s auto-dismiss. */
  onDismiss: () => void;
  isDisabled: () => boolean;
  /** Stop-generation action wired to the composer Stop button (Phase 10). */
  onStop?: () => void;
}

export interface ChatWindow {
  element: HTMLElement;
  composer: ChatComposer;
  suggested: HTMLElement;
  syncSuggested(questions: string[]): void;
  /** Set the banner to `banner`, or clear it with `null`. */
  setBanner(banner: BannerContent | null): void;
  /** Current banner message text ('' when none). */
  currentBanner(): string;
  /** Reflect the streaming state on the composer (Send ↔ Stop, Phase 10). */
  setStreaming(streaming: boolean): void;
  /** Announce status text via the visually-hidden live region (Phase 10). */
  setStatus(text: string): void;
  /** Re-apply branding/config to the header, composer placeholder and footer. */
  syncConfig(config: WidgetPublicConfig): void;
  /** Move focus to the composer (called when the window opens). */
  focusComposer(): void;
  /** Trap focus inside the window + focus the composer. */
  trapFocus(): void;
  /** Release the focus trap (called when the window closes). */
  releaseFocus(): void;
  /** Release timers so a destroyed widget never fires late callbacks. */
  dispose(): void;
}

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

/**
 * How long an error notification stays visible before auto-dismissing
 * (production hardening). The banner disappears on its own after 15s; the
 * conversation, partial answer and sources are untouched.
 */
export const BANNER_AUTO_DISMISS_MS = 15_000;

const CANONICAL_SITE_URL = (import.meta.env.VITE_SITE_URL ?? 'https://webchatai.com').replace(
  /\/$/,
  '',
);

export function createChatWindow(options: ChatWindowOptions): ChatWindow {
  const root = document.createElement('section');
  root.className = 'wc-window';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.hidden = true; // open()/close() own visibility (animations, not just attr)

  const titleId = 'wc-window-title';
  root.setAttribute('aria-labelledby', titleId);

  const header = document.createElement('header');
  header.className = 'wc-window-header';

  const headerLeft = document.createElement('div');
  headerLeft.className = 'wc-window-header-left';

  const brandIcon = document.createElement('span');
  brandIcon.className = 'wc-brand-icon';
  brandIcon.setAttribute('aria-hidden', 'true');
  const renderBrandIcon = (config: WidgetPublicConfig): void => {
    renderBrandLogo(brandIcon, config, 'wc-brand-logo');
  };
  renderBrandIcon(options.config);

  const titleBlock = document.createElement('div');
  titleBlock.className = 'wc-window-header-text';

  const heading = document.createElement('span');
  heading.id = titleId;
  heading.className = 'wc-window-brand';
  heading.textContent = options.config.bot_name;

  const statusLine = document.createElement('span');
  statusLine.className = 'wc-window-status';
  const statusDot = document.createElement('span');
  statusDot.className = 'wc-status-dot';
  statusDot.setAttribute('aria-hidden', 'true');
  const statusText = document.createElement('span');
  statusText.className = 'wc-status-text';
  statusText.textContent = options.config.bot_status_text;
  statusLine.appendChild(statusDot);
  statusLine.appendChild(statusText);

  titleBlock.appendChild(heading);
  titleBlock.appendChild(statusLine);
  headerLeft.appendChild(brandIcon);
  headerLeft.appendChild(titleBlock);

  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'wc-close';
  closeButton.setAttribute('aria-label', 'Close chat window');
  closeButton.appendChild(closeIcon());
  closeButton.addEventListener('click', options.onClose);

  header.appendChild(headerLeft);
  header.appendChild(closeButton);

  const footer = document.createElement('footer');
  footer.className = 'wc-window-footer';
  footer.setAttribute('role', 'contentinfo');
  footer.hidden = !options.config.branding;
  const footerText = document.createElement('span');
  footerText.appendChild(document.createTextNode('Powered by '));
  const footerLink = document.createElement('a');
  footerLink.className = 'wc-footer-link';
  footerLink.href = CANONICAL_SITE_URL;
  footerLink.target = '_blank';
  footerLink.rel = 'noopener noreferrer';
  footerLink.textContent = 'WebChat AI';
  footerLink.setAttribute('aria-label', 'Visit WebChat AI website');
  footerText.appendChild(footerLink);
  footer.appendChild(footerLogo());
  footer.appendChild(footerText);

  const status = document.createElement('div');
  status.className = 'wc-status-live';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');

  const banner = document.createElement('div');
  banner.className = 'wc-banner';
  banner.setAttribute('role', 'alert');
  banner.hidden = true;

  const bannerHeader = document.createElement('div');
  bannerHeader.className = 'wc-banner-header';

  const bannerTitle = document.createElement('span');
  bannerTitle.className = 'wc-banner-title';

  const bannerClose = document.createElement('button');
  bannerClose.type = 'button';
  bannerClose.className = 'wc-banner-close';
  bannerClose.setAttribute('aria-label', 'Dismiss error');
  bannerClose.appendChild(closeIcon());
  bannerClose.addEventListener('click', options.onDismiss);

  bannerHeader.appendChild(bannerTitle);
  bannerHeader.appendChild(bannerClose);

  const bannerMessage = document.createElement('p');
  bannerMessage.className = 'wc-banner-message';

  const bannerReference = document.createElement('span');
  bannerReference.className = 'wc-banner-reference';
  bannerReference.hidden = true;

  const retryButton = document.createElement('button');
  retryButton.type = 'button';
  retryButton.className = 'wc-banner-retry';
  retryButton.textContent = 'Retry';
  retryButton.addEventListener('click', options.onRetry);

  banner.appendChild(bannerHeader);
  banner.appendChild(bannerMessage);
  banner.appendChild(bannerReference);
  banner.appendChild(retryButton);

  // --- Banner auto-dismiss (production hardening) ---------------------------
  // The error notification disappears on its own 15s after it becomes visible.
  // The timer only (re)starts when the banner CONTENT changes: syncRenderer
  // re-asserts the same banner on every state pass, which must not keep
  // pushing the expiry out. Identical content is a no-op (no DOM writes, no
  // redundant alert re-announcements).

  let hideTimer: ReturnType<typeof setTimeout> | null = null;
  let lastBannerSignature: string | null = null;

  function clearHideTimer(): void {
    if (hideTimer !== null) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function showBanner(content: BannerContent): void {
    const signature = `${content.title}\u0000${content.message}\u0000${content.retryable}\u0000${content.requestId ?? ''}`;
    if (signature === lastBannerSignature && !banner.hidden) {
      return; // Same banner already rendered — leave the timer running.
    }
    lastBannerSignature = signature;
    bannerTitle.textContent = content.title;
    bannerMessage.textContent = content.message;
    bannerReference.hidden = !content.requestId;
    bannerReference.textContent = content.requestId ? `Reference: ${content.requestId}` : '';
    retryButton.hidden = !content.retryable;
    banner.hidden = false;
    clearHideTimer();
    // B & C: When a support reference/correlation ID exists, do NOT auto-dismiss
    // the banner after 15s. It must remain visible until the visitor dismisses (×),
    // clicks Retry, or a new turn replaces the state. Banners without a requestId
    // retain the existing 15s auto-dismiss countdown.
    if (!content.requestId) {
      hideTimer = setTimeout(() => {
        hideTimer = null;
        lastBannerSignature = null;
        clearBanner(); // Hide locally so dismissal is immediate regardless of caller.
        options.onDismiss();
      }, BANNER_AUTO_DISMISS_MS);
    }
  }

  function clearBanner(): void {
    clearHideTimer();
    lastBannerSignature = null;
    bannerTitle.textContent = '';
    bannerMessage.textContent = '';
    bannerReference.hidden = true;
    bannerReference.textContent = '';
    banner.hidden = true;
  }

  const messages = options.messagesElement;

  let suggested = createSuggested(options.config.suggested_questions, options.onSuggested);

  const composer = createComposer({
    placeholder: options.config.placeholder,
    onSend: options.onSend,
    isDisabled: options.isDisabled,
    onStop: options.onStop,
  });

  root.appendChild(header);
  root.appendChild(status);
  root.appendChild(banner);
  root.appendChild(messages);
  root.appendChild(suggested);
  root.appendChild(composer.element);
  root.appendChild(footer);

  // --- Focus management (WCAG 2.1.2, 2.4.3) --------------------------------

  function getFocusables(): HTMLElement[] {
    const nodes = root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    return Array.from(nodes).filter(
      (node) => !node.hidden && (!footer.hidden || !footer.contains(node)),
    );
  }

  let trapped = false;

  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') {
      // Audit W-05: the widget only owns Escape while focus lives inside the
      // dialog (same composedPath() check as the Tab branch). Escape pressed
      // elsewhere on the host page keeps driving host shortcuts (lightboxes,
      // sliders, ...) instead of closing this window.
      const target = event.composedPath()[0] as Node | null;
      if (!(target instanceof Node && root.contains(target))) {
        return;
      }
      event.preventDefault();
      options.onClose();
      return;
    }
    if (event.key !== 'Tab') {
      return;
    }
    const focusables = getFocusables();
    if (focusables.length === 0) {
      return;
    }
    // composedPath() pierces the closed shadow root so we can tell whether the
    // active element actually lives inside this window.
    const target = event.composedPath()[0] as Node | null;
    const index =
      target instanceof Node && root.contains(target)
        ? focusables.indexOf(target as HTMLElement)
        : -1;
    if (index === -1) {
      // Focus is on the launcher or the host page: pull it back into the dialog.
      event.preventDefault();
      focusables[0].focus();
      return;
    }
    if (event.shiftKey && index === 0) {
      event.preventDefault();
      focusables[focusables.length - 1].focus();
    } else if (!event.shiftKey && index === focusables.length - 1) {
      event.preventDefault();
      focusables[0].focus();
    }
  };

  const windowApi: ChatWindow = {
    element: root,
    composer,
    // `syncSuggested` replaces the element, so expose it via a live getter.
    get suggested() {
      return suggested;
    },
    syncSuggested(questions: string[]): void {
      const next = createSuggested(questions, options.onSuggested);
      suggested.replaceWith(next);
      suggested = next;
    },
    setBanner(content: BannerContent | null): void {
      if (content) {
        showBanner(content);
      } else {
        clearBanner();
      }
    },
    currentBanner(): string {
      return bannerMessage.textContent ?? '';
    },
    setStreaming(streaming: boolean): void {
      composer.setStreaming(streaming);
    },
    setStatus(text: string): void {
      status.textContent = text;
    },
    syncConfig(config: WidgetPublicConfig): void {
      heading.textContent = config.bot_name;
      statusText.textContent = config.bot_status_text;
      renderBrandIcon(config);
      composer.input.placeholder = config.placeholder;
      footer.hidden = !config.branding;
    },
    focusComposer(): void {
      composer.focus();
    },
    trapFocus(): void {
      if (trapped) {
        return;
      }
      trapped = true;
      // Capture phase: beat the host page's own Tab/Escape handling.
      document.addEventListener('keydown', onKeyDown, true);
      composer.focus();
    },
    releaseFocus(): void {
      if (!trapped) {
        return;
      }
      trapped = false;
      document.removeEventListener('keydown', onKeyDown, true);
    },
    dispose(): void {
      clearHideTimer();
      lastBannerSignature = null;
    },
  };

  return windowApi;
}
