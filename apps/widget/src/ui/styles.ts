/**
 * Widget UI styles (plan §5.1).
 *
 * Scoped to the shadow root. All theme values come from CSS custom properties
 * defined on the host element (`--wc-*`), inherited through the shadow
 * boundary. Uses rem/em units for 200%-zoom resilience and honors
 * `prefers-reduced-motion`.
 *
 * Self-containment (audit): the stylesheet references NO external assets
 * (no `url()`, `@font-face`, `@import` or font/image files).
 */

export const WIDGET_STYLES = `
  :host {
    --wc-primary: #2563eb;
    --wc-accent: #4f46e5;
    --wc-font-size: 16px;
    --wc-font-size-px: 16px;
    --wc-position: bottom-right;
    --wc-dark: 0;
    --wc-surface: #ffffff;
    --wc-surface-elevated: #ffffff;
    --wc-text: #1f2937;
    --wc-muted: #6b7280;
    --wc-border: #e5e7eb;
    --wc-bubble-bg: #f3f4f6;
    --wc-radius: 14px;
    --wc-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
    all: initial;
  }

  :host([data-dark='1']) {
    --wc-dark: 1;
    --wc-surface: #111827;
    --wc-surface-elevated: #1f2937;
    --wc-text: #f9fafb;
    --wc-muted: #9ca3af;
    --wc-border: #374151;
    --wc-bubble-bg: #1f2937;
    --wc-shadow: 0 8px 32px rgba(0, 0, 0, 0.55);
  }

  :host([data-widget]) {
    display: block;
  }

  /* The hidden attribute is an author-level signal: force it to win over any
     display rule below (e.g. .wc-window / .wc-launcher set display). */
  [hidden] {
    display: none !important;
  }

  .wc-shell {
    position: fixed;
    z-index: 2147483000;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 12px;
    box-sizing: border-box;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: var(--wc-font-size-px);
    line-height: 1.5;
    color: var(--wc-text);
  }

  .wc-shell[data-position='bottom-left'] {
    left: 16px;
    bottom: 16px;
  }

  .wc-shell[data-position='bottom-right'] {
    right: 16px;
    bottom: 16px;
  }

  /* While the dialog is open the launcher is hidden; closing the window
     (header X or Esc) reveals it again. */
  .wc-shell[data-open='true'] .wc-launcher {
    display: none;
  }

  /* ---- Launcher --------------------------------------------------------- */

  .wc-launcher {
    width: 58px;
    height: 58px;
    border: none;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--wc-primary), var(--wc-accent));
    color: #ffffff;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
    transition: transform 0.18s ease, box-shadow 0.18s ease;
    min-width: 24px;
    min-height: 24px;
  }

  .wc-launcher:hover {
    transform: translateY(-2px) scale(1.04);
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.26);
  }

  .wc-launcher:active {
    transform: scale(0.96);
  }

  .wc-launcher-icon {
    display: inline-flex;
  }

  .wc-launcher::before {
    content: '';
    position: absolute;
    inset: -3px;
    border-radius: 50%;
    border: 2px solid color-mix(in srgb, var(--wc-primary) 45%, transparent);
    animation: wc-launcher-pulse 2.4s ease-out infinite;
    pointer-events: none;
  }

  @keyframes wc-launcher-pulse {
    0% {
      opacity: 0.9;
      transform: scale(0.94);
    }
    70% {
      opacity: 0;
      transform: scale(1.12);
    }
    100% {
      opacity: 0;
    }
  }

  .wc-launcher:focus-visible,
  .wc-close:focus-visible,
  .wc-send:focus-visible,
  .wc-stop:focus-visible,
  .wc-retry-message:focus-visible,
  .wc-more-toggle:focus-visible,
  .wc-code-copy:focus-visible,
  .wc-chip:focus-visible,
  .wc-composer-input:focus-visible,
  .wc-thumb:focus-visible {
    outline: 2px solid var(--wc-accent);
    outline-offset: 2px;
  }

  /* ---- Chat window + open/close animations ------------------------------ */

  .wc-window {
    width: min(380px, calc(100vw - 32px));
    max-height: min(600px, calc(100vh - 32px));
    display: flex;
    flex-direction: column;
    background: var(--wc-surface);
    border: 1px solid var(--wc-border);
    border-radius: var(--wc-radius);
    box-shadow: var(--wc-shadow);
    overflow: hidden;
    transform-origin: bottom right;
    animation: wc-window-in 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  }

  .wc-shell[data-position='bottom-left'] .wc-window {
    transform-origin: bottom left;
  }

  @keyframes wc-window-in {
    from {
      opacity: 0;
      transform: translateY(24px) scale(0.97);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  .wc-window.wc-closing {
    animation: wc-window-out 0.18s ease-in forwards;
    pointer-events: none;
  }

  @keyframes wc-window-out {
    from {
      opacity: 1;
      transform: none;
    }
    to {
      opacity: 0;
      transform: scale(0.95);
    }
  }

  /* ---- Header ------------------------------------------------------------ */

  .wc-window-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 12px 14px;
    background: linear-gradient(135deg, var(--wc-primary), var(--wc-accent));
    color: #ffffff;
  }

  .wc-window-header-left {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  .wc-brand-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    flex: none;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.18);
    font-size: 18px;
    line-height: 1;
    overflow: hidden;
  }

  .wc-brand-logo {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .wc-window-header-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .wc-window-brand {
    font-weight: 600;
    font-size: 0.98em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .wc-window-status {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.72em;
    opacity: 0.92;
  }

  .wc-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #4ade80;
    box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.6);
    animation: wc-dot-pulse 1.8s ease-out infinite;
  }

  @keyframes wc-dot-pulse {
    0% {
      box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.55);
    }
    70% {
      box-shadow: 0 0 0 5px rgba(74, 222, 128, 0);
    }
    100% {
      box-shadow: 0 0 0 0 rgba(74, 222, 128, 0);
    }
  }

  .wc-close {
    flex: none;
    border: none;
    background: transparent;
    color: #ffffff;
    font-size: 22px;
    line-height: 1;
    cursor: pointer;
    width: 30px;
    height: 30px;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s ease;
  }

  .wc-close:hover {
    background: rgba(255, 255, 255, 0.18);
  }

  .wc-status-live,
  .wc-banner {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }

  .wc-banner {
    position: static;
    width: auto;
    height: auto;
    clip: auto;
    padding: 8px 16px;
    background: #fef2f2;
    color: #991b1b;
    font-size: 0.9em;
  }

  :host([data-dark='1']) .wc-banner {
    background: #451a03;
    color: #fecaca;
  }

  /* ---- Messages + bubbles ------------------------------------------------ */

  .wc-messages {
    flex: 1;
    overflow-y: auto;
    padding: 14px 14px 8px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 120px;
    overscroll-behavior: contain;
    touch-action: pan-y;
    -webkit-overflow-scrolling: touch;
  }

  .wc-empty-state {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin: auto auto 8px;
    max-width: 92%;
  }

  .wc-empty-avatar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 38px;
    flex: none;
    border-radius: 50%;
    background: color-mix(in srgb, var(--wc-primary) 12%, transparent);
    font-size: 20px;
    line-height: 1;
    overflow: hidden;
  }

  .wc-empty-avatar-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .wc-bubble {
    max-width: 82%;
    padding: 9px 13px;
    border-radius: 16px;
    font-size: 0.95em;
    word-wrap: break-word;
    overflow-wrap: break-word;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
    animation: wc-msg-in 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes wc-msg-in {
    from {
      opacity: 0;
      transform: translateY(6px) scale(0.985);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  .wc-role-user {
    align-self: flex-end;
    background: var(--wc-primary);
    color: #ffffff;
    border-bottom-right-radius: 6px;
  }

  .wc-role-assistant {
    align-self: flex-start;
    background: var(--wc-bubble-bg);
    color: var(--wc-text);
    border-bottom-left-radius: 6px;
  }

  .wc-bubble-text {
    white-space: pre-wrap;
  }

  .wc-time {
    display: block;
    margin-top: 4px;
    font-size: 0.68em;
    opacity: 0.6;
  }

  .wc-welcome {
    font-style: italic;
    opacity: 0.92;
  }

  .wc-streaming::after {
    content: '▍';
    margin-left: 1px;
    color: var(--wc-muted);
    animation: wc-caret 1s steps(2, start) infinite;
  }

  @keyframes wc-caret {
    from {
      opacity: 1;
    }
    to {
      opacity: 0.2;
    }
  }

  /* Animated "AI is typing" indicator while the turn has no content yet. */
  .wc-typing {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    color: var(--wc-muted);
  }

  .wc-typing-label {
    font-size: 0.82em;
    font-style: italic;
  }

  .wc-typing-dots {
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }

  .wc-typing-dots i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--wc-muted);
    animation: wc-typing-dot 1.2s ease-in-out infinite;
  }

  .wc-typing-dots i:nth-child(2) {
    animation-delay: 0.15s;
  }

  .wc-typing-dots i:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes wc-typing-dot {
    0%,
    60%,
    100% {
      opacity: 0.25;
      transform: translateY(0);
    }
    30% {
      opacity: 1;
      transform: translateY(-3px);
    }
  }

  .wc-bubble-error {
    border: 1px solid #fca5a5;
  }

  /* Partial answer kept after the user pressed Stop (Phase 10). */
  .wc-stopped .wc-bubble-content::after {
    content: ' (stopped)';
    color: var(--wc-muted);
    font-style: italic;
  }

  /* Per-message Retry action (Phase 10). */
  .wc-retry-message {
    display: block;
    margin-top: 8px;
    border: 1px solid var(--wc-border);
    background: var(--wc-surface-elevated);
    color: var(--wc-text);
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 0.85em;
    cursor: pointer;
    min-height: 24px;
  }

  /* Show more/less toggle for long answers (Phase 10). */
  .wc-long.wc-collapsed .wc-bubble-content {
    max-height: 180px;
    overflow: hidden;
    position: relative;
  }

  .wc-long.wc-collapsed .wc-bubble-content::after {
    content: '';
    position: absolute;
    inset: auto 0 0 0;
    height: 48px;
    background: linear-gradient(transparent, var(--wc-bubble-bg));
    pointer-events: none;
  }

  .wc-more-toggle {
    display: block;
    margin-top: 6px;
    border: none;
    background: transparent;
    color: var(--wc-primary);
    padding: 2px 0;
    font-size: 0.85em;
    cursor: pointer;
    text-decoration: underline;
    min-height: 24px;
  }

  /* Citation / source list (Phase 10). */
  .wc-sources {
    margin-top: 8px;
    padding-top: 6px;
    border-top: 1px solid var(--wc-border);
    font-size: 0.8em;
    color: var(--wc-muted);
  }

  .wc-sources-label {
    font-weight: 600;
  }

  .wc-sources-list {
    margin: 4px 0 0;
    padding-left: 18px;
  }

  .wc-sources-list a {
    color: var(--wc-primary);
  }

  /* Compact thumbs-only visitor feedback under completed answers. */
  .wc-feedback {
    margin-top: 9px;
    padding-top: 8px;
    border-top: 1px solid var(--wc-border);
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .wc-feedback-thumbs {
    display: flex;
    gap: 6px;
  }

  .wc-thumb {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border: 1px solid var(--wc-border);
    border-radius: 8px;
    background: var(--wc-surface-elevated);
    color: var(--wc-muted);
    cursor: pointer;
    min-height: 24px;
    transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
  }

  .wc-thumb:hover {
    color: var(--wc-primary);
    border-color: var(--wc-primary);
  }

  .wc-thumb[aria-pressed='true'] {
    color: var(--wc-primary);
    border-color: var(--wc-primary);
    background: color-mix(in srgb, var(--wc-primary) 12%, transparent);
  }

  .wc-thumb:disabled {
    opacity: 0.55;
    cursor: default;
  }

  .wc-feedback-note {
    color: var(--wc-muted);
    font-size: 0.82em;
    line-height: 1.3;
  }

  .wc-bubble-content h3,
  .wc-bubble-content h4,
  .wc-bubble-content h5,
  .wc-bubble-content h6 {
    margin: 0.5em 0 0.25em;
    font-size: 1.05em;
  }

  .wc-bubble-content p {
    margin: 0.3em 0;
  }

  .wc-bubble-content pre {
    background: #1f2937;
    color: #f9fafb;
    padding: 8px 10px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 0.85em;
  }

  .wc-bubble-content .wc-code {
    padding: 0;
    margin: 8px 0;
  }

  .wc-code-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.08);
    color: var(--wc-muted);
  }

  .wc-code-lang {
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .wc-code-copy {
    border: 1px solid rgba(255, 255, 255, 0.25);
    background: transparent;
    color: #e5e7eb;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 0.8em;
    cursor: pointer;
    min-height: 24px;
  }

  .wc-code-copy:hover {
    background: rgba(255, 255, 255, 0.12);
  }

  .wc-bubble-content code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.9em;
  }

  .wc-bubble-content a {
    color: var(--wc-primary);
    text-decoration: underline;
  }

  /* ---- Suggested questions ------------------------------------------------ */

  .wc-suggested {
    padding: 4px 16px 8px;
  }

  .wc-suggested-label {
    font-size: 0.8em;
    color: var(--wc-muted);
  }

  .wc-suggested-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
  }

  .wc-chip {
    border: 1px solid var(--wc-border);
    background: var(--wc-surface-elevated);
    color: var(--wc-text);
    border-radius: 999px;
    padding: 6px 12px;
    font-size: 0.85em;
    cursor: pointer;
    min-height: 24px;
    transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
  }

  .wc-chip:hover {
    border-color: var(--wc-primary);
    color: var(--wc-primary);
    background: color-mix(in srgb, var(--wc-primary) 6%, transparent);
  }

  /* ---- Composer ------------------------------------------------------------ */

  .wc-composer {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 10px 14px 14px;
    border-top: 1px solid var(--wc-border);
    background: var(--wc-surface);
  }

  .wc-composer-input {
    flex: 1;
    resize: none;
    border: 1px solid var(--wc-border);
    border-radius: 999px;
    padding: 10px 16px;
    font-size: 0.95em;
    font-family: inherit;
    color: var(--wc-text);
    background: var(--wc-surface-elevated);
    min-height: 40px;
    max-height: 120px;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.03);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  .wc-composer-input:focus {
    outline: none;
    border-color: var(--wc-primary);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--wc-primary) 18%, transparent);
  }

  .wc-send {
    flex: none;
    width: 42px;
    height: 42px;
    border: none;
    border-radius: 50%;
    background: var(--wc-primary);
    color: #ffffff;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 24px;
    transition: background 0.15s ease, transform 0.15s ease;
  }

  .wc-send:hover:not(:disabled) {
    transform: translateY(-1px);
    background: color-mix(in srgb, var(--wc-primary) 88%, #000000);
  }

  .wc-send:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
  }

  /* Loading spinner replaces the send icon while a reply is pending. */
  .wc-send-spinner {
    display: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.35);
    border-top-color: #ffffff;
    animation: wc-spin 0.7s linear infinite;
  }

  .wc-composer.wc-busy .wc-send-spinner {
    display: block;
  }

  .wc-composer.wc-busy .wc-send svg {
    display: none;
  }

  @keyframes wc-spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* Stop-generation button, swaps in while a turn streams (Phase 10). */
  .wc-stop {
    flex: none;
    width: 42px;
    height: 42px;
    border: 1px solid #fca5a5;
    background: #fee2e2;
    color: #991b1b;
    border-radius: 50%;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 24px;
  }

  :host([data-dark='1']) .wc-stop {
    background: #451a03;
    color: #fecaca;
  }

  /* ---- Reduced motion ------------------------------------------------------- */

  @media (prefers-reduced-motion: reduce) {
    .wc-launcher,
    .wc-launcher::before,
    .wc-window,
    .wc-bubble,
    .wc-streaming::after,
    .wc-typing-dots i,
    .wc-status-dot,
    .wc-send-spinner,
    .wc-send,
    .wc-close,
    .wc-thumb,
    .wc-chip {
      transition: none;
      animation: none;
    }
  }

  /* ---- Mobile ---------------------------------------------------------------- */

  @media (max-width: 480px) {
    .wc-shell[data-position='bottom-left'],
    .wc-shell[data-position='bottom-right'] {
      left: 0;
      right: 0;
      bottom: 0;
    }

    .wc-window {
      width: 100%;
      max-height: calc(100vh - 84px);
      border-radius: 16px 16px 0 0;
    }

    @supports (height: 100dvh) {
      .wc-window {
        max-height: calc(100dvh - 84px);
      }
    }

    .wc-shell[data-position='bottom-right'] .wc-launcher {
      margin-right: 16px;
      margin-bottom: 16px;
    }

    .wc-shell[data-position='bottom-left'] .wc-launcher {
      margin-left: 16px;
      margin-bottom: 16px;
    }
  }
`;
