/**
 * Widget UI styles (plan §5.1).
 *
 * Scoped to the shadow root. All theme values come from CSS custom properties
 * defined on the host element (`--wc-*`), inherited through the shadow
 * boundary. Uses rem/em units for 200%-zoom resilience and honors
 * `prefers-reduced-motion`.
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
    --wc-radius: 12px;
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

  .wc-shell {
    position: fixed;
    z-index: 2147483000;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 12px;
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

  .wc-launcher {
    width: 56px;
    height: 56px;
    border: none;
    border-radius: 50%;
    background: var(--wc-primary);
    color: #ffffff;
    font-size: 24px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: var(--wc-shadow);
    transition: transform 0.15s ease;
    min-width: 24px;
    min-height: 24px;
  }

  .wc-launcher:hover {
    transform: scale(1.05);
  }

  .wc-launcher:focus-visible,
  .wc-close:focus-visible,
  .wc-send:focus-visible,
  .wc-chip:focus-visible,
  .wc-composer-input:focus-visible {
    outline: 2px solid var(--wc-accent);
    outline-offset: 2px;
  }

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
    animation: wc-window-in 0.18s ease-out;
  }

  @keyframes wc-window-in {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  .wc-window-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    background: var(--wc-primary);
    color: #ffffff;
  }

  .wc-window-brand {
    font-weight: 600;
  }

  .wc-close {
    border: none;
    background: transparent;
    color: #ffffff;
    font-size: 20px;
    line-height: 1;
    cursor: pointer;
    width: 28px;
    height: 28px;
    border-radius: 6px;
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

  .wc-messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 120px;
  }

  .wc-bubble {
    max-width: 82%;
    padding: 8px 12px;
    border-radius: 12px;
    font-size: 0.95em;
    word-wrap: break-word;
  }

  .wc-role-user {
    align-self: flex-end;
    background: var(--wc-primary);
    color: #ffffff;
    border-bottom-right-radius: 4px;
  }

  .wc-role-assistant {
    align-self: flex-start;
    background: var(--wc-bubble-bg);
    color: var(--wc-text);
    border-bottom-left-radius: 4px;
  }

  .wc-welcome {
    font-style: italic;
    opacity: 0.9;
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

  .wc-bubble-error {
    border: 1px solid #fca5a5;
  }

  .wc-bubble-content h3,
  .wc-bubble-content h4,
  .wc-bubble-content h5,
  .wc-bubble-content h6 {
    margin: 0.5em 0 0.25em;
    font-size: 1.05em;
  }

  .wc-bubble-content pre {
    background: #1f2937;
    color: #f9fafb;
    padding: 8px 10px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 0.85em;
  }

  .wc-bubble-content code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.9em;
  }

  .wc-bubble-content a {
    color: var(--wc-primary);
    text-decoration: underline;
  }

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
  }

  .wc-composer {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 12px 16px;
    border-top: 1px solid var(--wc-border);
  }

  .wc-composer-input {
    flex: 1;
    resize: none;
    border: 1px solid var(--wc-border);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.95em;
    font-family: inherit;
    color: var(--wc-text);
    background: var(--wc-surface-elevated);
    min-height: 40px;
    max-height: 120px;
  }

  .wc-counter {
    font-size: 0.75em;
    color: var(--wc-muted);
  }

  .wc-send {
    border: none;
    background: var(--wc-primary);
    color: #ffffff;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 0.9em;
    cursor: pointer;
    min-height: 40px;
  }

  .wc-send:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  @media (prefers-reduced-motion: reduce) {
    .wc-launcher,
    .wc-window,
    .wc-streaming::after {
      transition: none;
      animation: none;
    }
  }

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
      border-radius: 12px 12px 0 0;
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
