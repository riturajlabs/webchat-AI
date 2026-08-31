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
    --wc-primary: #10A37F;
    --wc-accent: #25D366;
    --wc-secondary: #25D366;
    --wc-header-color: linear-gradient(135deg, var(--wc-primary), var(--wc-secondary));
    --wc-header-bg: linear-gradient(135deg, var(--wc-primary), var(--wc-secondary));
    --wc-header-text: #ffffff;
    --wc-font-size: 16px;
    --wc-font-size-px: 16px;
    --wc-font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    --wc-position: bottom-right;
    --wc-dark: 0;
    --wc-surface: #ffffff;
    --wc-surface-elevated: #ffffff;
    --wc-text: #1f2937;
    --wc-muted: #6b7280;
    --wc-border: #e5e7eb;
    --wc-bubble-bg: #f3f4f6;
    --wc-user-bubble: var(--wc-primary);
    --wc-user-text: #ffffff;
    --wc-input-bg: var(--wc-surface-elevated);
    --wc-scrollbar-thumb: rgba(100, 116, 139, 0.35);
    --wc-scrollbar-track: #eef2f7;
    --wc-send-button: linear-gradient(135deg, var(--wc-primary), var(--wc-secondary));
    --wc-send-button-foreground: #ffffff;
    --wc-launcher-bg: linear-gradient(135deg, var(--wc-primary), var(--wc-accent));
    --wc-launcher-fg: #ffffff;
    --wc-close-button-fg: #ffffff;
    --wc-suggestion-bg: var(--wc-surface-elevated);
    --wc-suggestion-fg: var(--wc-text);
    --wc-suggestion-border: var(--wc-border);
    --wc-input-border: var(--wc-border);
    --wc-focus-ring: var(--wc-accent);
    --wc-online-indicator: #4ade80;
    --wc-radius: 20px;
    --wc-width: 380px;
    --wc-height: 600px;
    --wc-launcher-size: 58px;
    --wc-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
    --wc-error: #ef4444;
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
    --wc-input-bg: #1f2937;
    --wc-scrollbar-thumb: rgba(148, 163, 184, 0.35);
    --wc-scrollbar-track: #0f172a;
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
    /* Audit W-06: lifted above the on-screen keyboard via the visual-viewport
       inset wired in mount (--wc-keyboard-inset; 0px when absent). */
    bottom: calc(16px + var(--wc-keyboard-inset, 0px));
  }

  .wc-shell[data-position='bottom-right'] {
    right: 16px;
    bottom: calc(16px + var(--wc-keyboard-inset, 0px));
  }

  /* While the dialog is open the launcher is hidden; closing the window
     (header X or Esc) reveals it again. */
  .wc-shell[data-open='true'] .wc-launcher {
    display: none;
  }

  /* ---- Launcher --------------------------------------------------------- */

  .wc-launcher {
    width: var(--wc-launcher-size);
    height: var(--wc-launcher-size);
    border: none;
    border-radius: 50%;
    background: var(--wc-launcher-bg, linear-gradient(135deg, var(--wc-primary), var(--wc-accent)));
    color: var(--wc-launcher-fg, var(--wc-on-primary, #ffffff));
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
  .wc-star:focus-visible {
    outline: 2px solid var(--wc-focus-ring, var(--wc-accent));
    outline-offset: 2px;
  }

  /* ---- Chat window + open/close animations ------------------------------ */

  .wc-window {
    width: min(var(--wc-width), calc(100vw - 24px));
    /* Audit W-06: shrink with the visible viewport so the composer is never
       occluded by the on-screen keyboard. */
    height: min(var(--wc-height), calc(100vh - 24px - var(--wc-keyboard-inset, 0px)));
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
    background: var(--wc-header-bg, linear-gradient(135deg, var(--wc-primary), var(--wc-secondary)));
    color: var(--wc-header-text, #ffffff);
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
    background: color-mix(in srgb, var(--wc-header-text, #ffffff) 18%, transparent);
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
    background: var(--wc-online-indicator, #4ade80);
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--wc-online-indicator, #4ade80) 60%, transparent);
    animation: wc-dot-pulse 1.8s ease-out infinite;
  }

  @keyframes wc-dot-pulse {
    0% {
      box-shadow: 0 0 0 0 color-mix(in srgb, var(--wc-online-indicator, #4ade80) 55%, transparent);
    }
    70% {
      box-shadow: 0 0 0 5px color-mix(in srgb, var(--wc-online-indicator, #4ade80) 0%, transparent);
    }
    100% {
      box-shadow: 0 0 0 0 color-mix(in srgb, var(--wc-online-indicator, #4ade80) 0%, transparent);
    }
  }

  .wc-close {
    flex: none;
    border: none;
    background: transparent;
    color: var(--wc-close-button-fg, var(--wc-header-text, #ffffff));
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
    background: color-mix(in srgb, var(--wc-close-button-fg, var(--wc-header-text, #ffffff)) 18%, transparent);
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
    background: color-mix(in srgb, var(--wc-error, #ef4444) 12%, transparent);
    color: var(--wc-error, #ef4444);
    font-size: 0.9em;
  }

  :host([data-dark='1']) .wc-banner {
    background: color-mix(in srgb, var(--wc-error, #ef4444) 18%, transparent);
    color: color-mix(in srgb, var(--wc-error, #ef4444) 85%, #ffffff);
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
    scrollbar-width: thin;
    scrollbar-color: var(--wc-scrollbar-thumb, rgba(100, 116, 139, 0.35))
      var(--wc-scrollbar-track, transparent);
  }

  .wc-messages::-webkit-scrollbar {
    width: 8px;
  }

  .wc-messages::-webkit-scrollbar-track {
    background: var(--wc-scrollbar-track, transparent);
  }

  .wc-messages::-webkit-scrollbar-thumb {
    background: var(--wc-scrollbar-thumb, rgba(100, 116, 139, 0.35));
    border-radius: 999px;
  }

  .wc-messages::-webkit-scrollbar-thumb:hover {
    background: var(--wc-scrollbar-thumb, rgba(100, 116, 139, 0.35));
    filter: brightness(1.1);
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
    background: var(--wc-user-bubble, var(--wc-primary));
    color: var(--wc-user-text, #ffffff);
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

  /* Animated typing indicator — three dots only (no text label). */
  .wc-typing {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 8px 12px;
    border-radius: 16px;
    background: var(--wc-bubble-bg, var(--wc-surface-elevated));
  }

  .wc-typing-dots {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .wc-typing-dots i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--wc-muted);
    animation: wc-typing-dot 1.4s ease-in-out infinite;
  }

  .wc-typing-dots i:nth-child(2) {
    animation-delay: 0.2s;
  }

  .wc-typing-dots i:nth-child(3) {
    animation-delay: 0.4s;
  }

  @keyframes wc-typing-dot {
    0%,
    60%,
    100% {
      opacity: 0.3;
      transform: translateY(0);
    }
    30% {
      opacity: 1;
      transform: translateY(-4px);
    }
  }

  .wc-bubble-error {
    border: 1px solid color-mix(in srgb, var(--wc-error, #ef4444) 50%, transparent);
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

  /* "Learn more" citation cards: compact, clean layout with external link. */
  .wc-sources {
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid var(--wc-border);
    font-size: 0.8em;
    color: var(--wc-muted);
  }

  .wc-sources-label {
    display: block;
    font-weight: 600;
    margin-bottom: 6px;
    color: var(--wc-text);
    font-size: 0.85em;
    letter-spacing: 0.02em;
  }

  .wc-sources-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    scrollbar-color: var(--wc-scrollbar-thumb, rgba(100, 116, 139, 0.35))
      var(--wc-scrollbar-track, transparent);
  }

  .wc-sources-expanded .wc-sources-list {
    max-height: 260px;
    overflow-y: auto;
  }

  .wc-sources-list::-webkit-scrollbar {
    width: 6px;
  }

  .wc-sources-list::-webkit-scrollbar-track {
    background: var(--wc-scrollbar-track, transparent);
  }

  .wc-sources-list::-webkit-scrollbar-thumb {
    background: var(--wc-scrollbar-thumb, rgba(100, 116, 139, 0.35));
    border-radius: 999px;
  }

  .wc-source-item {
    margin: 0;
  }

  /* Cards past the first three stay hidden until the toggle expands them. */
  .wc-source-item.wc-source-hidden {
    display: none;
  }

  .wc-sources-expanded .wc-source-item.wc-source-hidden {
    display: block;
  }

  /* Inline citation chip upgraded from a "[n]" marker (audit W-09): clicking
     jumps to the matching "Learn more" card. */
  .wc-citation {
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    vertical-align: baseline;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    margin: 0 2px;
    border: 1px solid var(--wc-border);
    border-radius: 999px;
    background: var(--wc-surface-elevated);
    color: var(--wc-muted);
    font-size: 0.7em;
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
  }

  .wc-citation:hover,
  .wc-citation:focus-visible {
    color: var(--wc-primary);
    border-color: var(--wc-primary);
  }

  .wc-citation:focus-visible {
    outline: 2px solid var(--wc-focus-ring, var(--wc-accent));
    outline-offset: 2px;
  }

  /* One-shot flash on the card an inline citation navigated to. */
  @keyframes wc-source-flash {
    0%,
    40% {
      border-color: var(--wc-accent);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--wc-accent, #f59e0b) 25%, transparent);
    }
    100% {
      border-color: var(--wc-border);
      box-shadow: none;
    }
  }

  .wc-source-item.wc-source-highlight .wc-source-link {
    animation: wc-source-flash 1.4s ease-out 1;
  }

  .wc-source-link {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 8px;
    align-items: center;
    color: var(--wc-text);
    text-decoration: none;
    border: 1px solid var(--wc-border);
    border-radius: 10px;
    padding: 8px 10px;
    background: var(--wc-surface-elevated);
    transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease,
      box-shadow 0.15s ease;
  }

  a.wc-source-link {
    cursor: pointer;
  }

  a.wc-source-link:hover {
    border-color: var(--wc-primary);
    background: color-mix(in srgb, var(--wc-primary) 6%, transparent);
    transform: translateY(-1px);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  }

  a.wc-source-link:hover .wc-source-title {
    color: var(--wc-primary);
  }

  a.wc-source-link:focus-visible {
    outline: 2px solid var(--wc-primary);
    outline-offset: 2px;
  }

  .wc-source-link-plain {
    color: var(--wc-muted);
  }

  .wc-source-citation {
    grid-column: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: 999px;
    border: 1px solid var(--wc-border);
    background: var(--wc-surface);
    color: var(--wc-muted);
    font-size: 0.7em;
    font-weight: 600;
    line-height: 1;
  }

  .wc-source-favicon {
    display: none;
  }

  .wc-source-favicon img {
    display: none;
  }

  .wc-source-body {
    grid-column: 1;
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }

  .wc-source-title {
    font-weight: 600;
    color: var(--wc-text);
    font-size: 0.92em;
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
    transition: color 0.15s ease;
  }

  .wc-source-desc {
    color: var(--wc-muted);
    font-size: 0.85em;
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  .wc-source-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 1px;
    min-width: 0;
  }

  .wc-source-url {
    flex: 1;
    min-width: 0;
    color: var(--wc-muted);
    font-size: 0.75em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .wc-source-read {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    color: var(--wc-primary);
    font-weight: 600;
    font-size: 0.78em;
    white-space: nowrap;
  }

  a.wc-source-link:hover .wc-source-read {
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .wc-sources-toggle {
    display: block;
    margin: 6px 0 0;
    padding: 4px 2px;
    border: none;
    background: transparent;
    color: var(--wc-primary);
    font-size: 0.8em;
    font-weight: 600;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .wc-sources-toggle:hover {
    opacity: 0.85;
  }

  .wc-sources-toggle:focus-visible {
    outline: 2px solid var(--wc-primary);
    outline-offset: 2px;
  }

  /* Narrow viewports: let the "Read more" affordance wrap under the URL. */
  @media (max-width: 420px) {
    .wc-source-meta {
      flex-wrap: wrap;
    }

    .wc-source-read {
      width: 100%;
    }
  }

  /* Compact 5-star visitor feedback under completed answers. */
  .wc-feedback {
    margin-top: 9px;
    padding-top: 8px;
    border-top: 1px solid var(--wc-border);
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .wc-feedback-stars {
    display: inline-flex;
    gap: 2px;
  }

  .wc-star {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--wc-muted);
    cursor: pointer;
    min-height: 24px;
    transition: color 0.15s ease, transform 0.15s ease;
  }

  .wc-star svg {
    transition: transform 0.15s ease;
  }

  .wc-star:hover:not(:disabled) {
    color: var(--wc-warning, var(--wc-primary));
    transform: translateY(-1px);
  }

  .wc-star:hover:not(:disabled) svg {
    transform: scale(1.12);
  }

  .wc-star:active:not(:disabled) {
    transform: scale(0.9);
  }

  .wc-star[aria-pressed='true'] {
    color: var(--wc-warning, var(--wc-primary));
  }

  .wc-star[aria-pressed='true'] svg {
    fill: currentColor;
  }

  .wc-star:disabled {
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
    margin: 0.6em 0 0.25em;
    font-size: 1.05em;
    line-height: 1.35;
  }

  .wc-bubble-content p {
    margin: 0.35em 0;
  }

  .wc-bubble-content ul,
  .wc-bubble-content ol {
    margin: 0.4em 0 0.4em;
    padding-left: 1.35em;
  }

  .wc-bubble-content li {
    margin: 0.18em 0;
  }

  .wc-bubble-content blockquote {
    margin: 0.5em 0;
    padding: 2px 12px;
    border-left: 3px solid var(--wc-border);
    color: var(--wc-muted);
  }

  .wc-bubble-content table {
    width: 100%;
    margin: 0.5em 0;
    border-collapse: collapse;
    font-size: 0.92em;
  }

  .wc-bubble-content th,
  .wc-bubble-content td {
    border: 1px solid var(--wc-border);
    padding: 6px 9px;
    text-align: left;
  }

  .wc-bubble-content th {
    background: var(--wc-surface-elevated);
    font-weight: 600;
  }

  .wc-bubble-content pre {
    background: #1f2937;
    color: #f9fafb;
    padding: 8px 10px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 0.85em;
    margin: 0.5em 0;
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
    border: 1px solid var(--wc-suggestion-border, var(--wc-border));
    background: var(--wc-suggestion-bg, var(--wc-surface-elevated));
    color: var(--wc-suggestion-fg, var(--wc-text));
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
    padding: 8px 12px 10px;
    border-top: 1px solid var(--wc-border);
    background: var(--wc-surface);
  }

  /* Compact pill: input + send/stop in one rounded container. */
  .wc-composer-pill {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 3px 4px 3px 14px;
    border: 1px solid var(--wc-input-border, var(--wc-border));
    border-radius: 22px;
    background: var(--wc-input-bg, var(--wc-surface-elevated));
    box-shadow:
    0 2px 8px rgba(0,0,0,0.08),
    0 1px 2px rgba(0,0,0,0.04);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  .wc-composer-pill:focus-within {
    border-color: var(--wc-focus-ring, var(--wc-primary));
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--wc-focus-ring, var(--wc-primary)) 18%, transparent);
  }

  .wc-composer-input {
    flex: 1;
    resize: none;
    border: none;
    background: transparent;

    padding: 5px 0;

    font-size: 0.93em;
    font-family: inherit;
    color: var(--wc-text);

    min-height: 28px;
    max-height: 88px;

    display: flex;
    align-items: center;

    box-shadow: none;
    outline: none;

    line-height: 1.35;
  }

 .wc-composer-input::placeholder {
    color: var(--wc-muted);
    opacity:0.65;
    transition:opacity .2s ease;
}


.wc-composer-input:focus::placeholder {
    opacity:0.4;
}

  .wc-send {
    flex: none;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 50%;
    background: var(--wc-send-button, linear-gradient(135deg, var(--wc-primary), var(--wc-secondary)));
    color: var(--wc-send-button-foreground, var(--wc-on-primary, #ffffff));
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 20px;
    transition: background 0.15s ease, transform 0.15s ease, opacity 0.15s ease,
      box-shadow 0.15s ease;
  }

  .wc-send:hover:not(:disabled) {
    transform: translateY(-2px) scale(1.08);
    box-shadow:
      0 6px 14px
      color-mix(in srgb,var(--wc-primary) 35%,transparent);
  }

  .wc-send:active:not(:disabled) {
    transform: scale(0.94);
  }

  .wc-send:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    transform: none;
  }

  /* Loading spinner replaces the send icon while a reply is pending. */
  .wc-send-spinner {
    display: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 2px solid color-mix(in srgb, var(--wc-send-button-foreground, var(--wc-on-primary, #ffffff)) 35%, transparent);
    border-top-color: var(--wc-send-button-foreground, var(--wc-on-primary, #ffffff));
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

  /* Stop-generation button — filled circle with square icon, animated pulse. */
  .wc-stop {
    flex: none;
    width: 32px;
    height: 32px;
    border: 2px solid var(--wc-primary);
    background: transparent;
    color: var(--wc-primary);
    border-radius: 50%;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 20px;
    position: relative;
    transition: background 0.15s ease, transform 0.15s ease, border-color 0.15s ease;
    animation: wc-stop-pulse 2s ease-in-out infinite;
  }

  .wc-stop:hover {
    background: color-mix(in srgb, var(--wc-primary) 12%, transparent);
    transform: scale(1.05);
  }

  .wc-stop:active {
    transform: scale(0.94);
  }

  @keyframes wc-stop-pulse {
    0%,
    100% {
      box-shadow: 0 0 0 0 color-mix(in srgb, var(--wc-primary) 30%, transparent);
    }
    50% {
      box-shadow: 0 0 0 5px color-mix(in srgb, var(--wc-primary) 0%, transparent);
    }
  }

  :host([data-dark='1']) .wc-stop {
    border-color: var(--wc-primary);
    color: var(--wc-primary);
  }

  :host([data-dark='1']) .wc-stop:hover {
    background: color-mix(in srgb, var(--wc-primary) 18%, transparent);
  }

  /* ---- Footer --------------------------------------------------------------- */

  .wc-window-footer {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 5px 12px;
    border-top: 1px solid var(--wc-border);
    background: var(--wc-surface);
    font-size: 0.72em;
    color: var(--wc-muted);
  }

  .wc-footer-logo {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--wc-primary);
  }

  .wc-footer-link {
    color: inherit;
    text-decoration: none;
  }

  .wc-footer-link:hover {
    color: var(--wc-primary);
  }

  /* ---- Reduced motion ------------------------------------------------------- */

  @media (prefers-reduced-motion: reduce) {
    .wc-launcher,
    .wc-launcher::before,
    .wc-window,
    .wc-bubble,
    .wc-typing-dots i,
    .wc-status-dot,
    .wc-send-spinner,
    .wc-send,
    .wc-close,
    .wc-star,
    .wc-chip {
      transition: none;
      animation: none;
    }
  }

  /* ---- Mobile ---------------------------------------------------------------- */

  @media (max-width: 480px) {
    .wc-shell[data-position='bottom-left'],
    .wc-shell[data-position='bottom-right'] {
      left: 12px;
      right: 12px;
      bottom: 12px;
    }

    .wc-window {
      width: min(var(--wc-width), calc(100vw - 24px));
      height: min(var(--wc-height), calc(100vh - 120px));
      border-radius: var(--wc-radius);
    }

    @supports (height: 100dvh) {
      .wc-window {
        height: min(var(--wc-height), calc(100dvh - 120px));
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
