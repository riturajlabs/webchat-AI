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
import { createComposer } from './composer';
import type { ChatComposer } from './composer';
import { createSuggested } from './suggested';

export interface ChatWindowOptions {
  config: WidgetPublicConfig;
  messagesElement: HTMLElement;
  onSend: (question: string) => void;
  onClose: () => void;
  onSuggested: (question: string) => void;
  /** Re-send the last failed question (plan §9 retry action). */
  onRetry: () => void;
  /** Dismiss the banner (plan §9). */
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
  /** `retryable` shows the Retry action alongside the message. */
  setBanner(message: string | null, retryable?: boolean): void;
  /** Current banner message text ('' when none). */
  currentBanner(): string;
  /** Reflect the streaming state on the composer (Send ↔ Stop, Phase 10). */
  setStreaming(streaming: boolean): void;
  /** Announce status text via the visually-hidden live region (Phase 10). */
  setStatus(text: string): void;
  /** Move focus to the composer (called when the window opens). */
  focusComposer(): void;
  /** Trap focus inside the window + focus the composer. */
  trapFocus(): void;
  /** Release the focus trap (called when the window closes). */
  releaseFocus(): void;
}

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function createChatWindow(options: ChatWindowOptions): ChatWindow {
  const root = document.createElement('section');
  root.className = 'wc-window';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');

  const titleId = 'wc-window-title';
  root.setAttribute('aria-labelledby', titleId);

  const header = document.createElement('header');
  header.className = 'wc-window-header';

  const title = document.createElement('div');
  title.id = titleId;
  title.className = 'wc-window-title';
  const heading = document.createElement('span');
  heading.className = 'wc-window-brand';
  heading.textContent = options.config.branding ? 'WebChat AI' : 'Assistant';
  title.appendChild(heading);

  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'wc-close';
  closeButton.setAttribute('aria-label', 'Close chat window');
  closeButton.textContent = '×';
  closeButton.addEventListener('click', options.onClose);

  header.appendChild(title);
  header.appendChild(closeButton);

  const status = document.createElement('div');
  status.className = 'wc-status-live';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');

  const banner = document.createElement('div');
  banner.className = 'wc-banner';
  banner.setAttribute('role', 'alert');
  banner.hidden = true;

  const bannerMessage = document.createElement('span');
  bannerMessage.className = 'wc-banner-message';

  const retryButton = document.createElement('button');
  retryButton.type = 'button';
  retryButton.className = 'wc-banner-retry';
  retryButton.textContent = 'Retry';
  retryButton.addEventListener('click', options.onRetry);

  const dismissButton = document.createElement('button');
  dismissButton.type = 'button';
  dismissButton.className = 'wc-banner-dismiss';
  dismissButton.textContent = 'Dismiss';
  dismissButton.addEventListener('click', options.onDismiss);

  banner.appendChild(bannerMessage);
  banner.appendChild(retryButton);
  banner.appendChild(dismissButton);

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

  // --- Focus management (WCAG 2.1.2, 2.4.3) --------------------------------

  function getFocusables(): HTMLElement[] {
    const nodes = root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    return Array.from(nodes).filter((node) => !node.hidden);
  }

  let trapped = false;

  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') {
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
    suggested,
    syncSuggested(questions: string[]): void {
      const next = createSuggested(questions, options.onSuggested);
      suggested.replaceWith(next);
      suggested = next;
    },
    setBanner(message: string | null, retryable = false): void {
      bannerMessage.textContent = message ?? '';
      banner.hidden = !message;
      retryButton.hidden = !message || !retryable;
      dismissButton.hidden = !message;
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
  };

  return windowApi;
}
