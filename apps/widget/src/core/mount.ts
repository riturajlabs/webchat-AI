/**
 * Widget lifecycle (plan §5.1, ADR-004).
 *
 * `mount()` attaches a **closed** shadow root to the host `<webchat-widget>`
 * element, wires the core services (visitor identity, session tokens, config)
 * and renders the UI (launcher + chat window) into the shadow root. The theme
 * is applied via CSS custom properties on the host element.
 *
 * Phase 10: streaming UX — an `AbortController` per turn powers the composer
 * Stop button (`streamChat` returns `{ aborted }`, the partial answer is kept
 * and marked `stopped`, never an error); `sources` events are attached to the
 * assistant turn; bubble actions (copy code, per-message Retry, show-more) are
 * delegated from `mount` via `wireMessageActions`.
 */

import { loadConfig, type ConfigStore } from '../config/fetch';
import {
  defaultConfig,
  resolveApiBaseUrl,
  type WidgetOptions,
  type WidgetPublicConfig,
} from '../config/types';
import { SessionManager } from './session';
import { getVisitorId } from './visitor';
import { isOffline } from './network';
import { applyTheme, prefersReducedMotion } from '../theme/apply';
import { createLauncher, syncLauncher } from '../ui/launcher';
import { createChatWindow } from '../ui/window';
import {
  createMessageList,
  createWelcomeBubble,
  renderMessages,
  setBusy,
  toggleExpanded,
  wireMessageActions,
} from '../ui/bubbles';
import { submitFeedback } from '../feedback/api';
import type { FeedbackSubmitPayload } from '../ui/feedback';
import type { FeedbackState } from '../stream/chat';
import { WIDGET_STYLES } from '../ui/styles';
import { streamChat } from '../stream/client';
import { Conversation, type ChatMessage } from '../stream/chat';
import type { WidgetError } from './errors';

/** Banner shown while the browser reports itself offline (plan §9). */
export const OFFLINE_BANNER = "You're offline. Messages will be sent once your connection returns.";

/** Banner shown when the backend reports the widget as disabled/suspended. */
export const WIDGET_UNAVAILABLE_BANNER = 'This assistant is currently unavailable.';

export interface WidgetHostOptions extends WidgetOptions {
  /** The `<webchat-widget>` element to attach to. Created + appended when omitted. */
  host?: HTMLElement;
  /** Attach immediately (embed flow). Programmatic callers may defer. */
  autoStart?: boolean;
  /** Test seams. */
  fetchImpl?: typeof fetch;
  configStore?: ConfigStore;
}

export interface WidgetController {
  readonly widgetId: string;
  readonly apiBaseUrl: string;
  readonly visitorId: string;
  readonly session: SessionManager;
  /** Currently resolved public config (defaults until config loads). */
  getConfig(): WidgetPublicConfig;
  /** Resolves once the public config has been fetched (or defaulted). */
  ready(): Promise<WidgetPublicConfig>;
  /** Whether a chat window is currently open. */
  isOpen(): boolean;
  /** Open / close the chat window. */
  open(): void;
  close(): void;
  /** Send a question programmatically (Phase 10 test/embed seam). */
  sendMessage(question: string): void;
  /** Tear down the widget and detach the host element. */
  destroy(): void;
}

const HOST_TAG = 'webchat-widget';

/** Register the custom element once (idempotent across HMR / re-imports). */
export function defineWidgetElement(): void {
  if (!globalThis.customElements?.get(HOST_TAG)) {
    class WebChatWidgetElement extends HTMLElement {}
    globalThis.customElements?.define(HOST_TAG, WebChatWidgetElement);
  }
}

/** Copy text to the clipboard with a legacy fallback (Phase 10). */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the legacy path.
    }
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

/**
 * Mount the widget into `host` (or a fresh `<webchat-widget>` appended to the
 * document body) and return a controller.
 */
export function mount(options: WidgetHostOptions): WidgetController {
  const widgetId = options.widgetId;
  const apiBaseUrl = resolveApiBaseUrl(options.apiBaseUrl);
  const fetchImpl = options.fetchImpl ?? fetch;
  const configStore = options.configStore;

  const host = options.host ?? createHost(widgetId, apiBaseUrl);
  const shadowRoot = host.shadowRoot ?? host.attachShadow({ mode: 'closed' });

  const visitorId = getVisitorId();
  const session = new SessionManager({ widgetId, apiBaseUrl }, visitorId, fetchImpl);
  const conversation = new Conversation();

  let currentConfig: WidgetPublicConfig = defaultConfig(widgetId);
  let configLoaded = false;
  const configWaiters: Array<(config: WidgetPublicConfig) => void> = [];
  let destroyed = false;
  let open = false;
  /**
   * True when the fetched config reports `enabled: false` (widget disabled by
   * its tenant, or tenant suspended). Chat is blocked and a persistent banner
   * explains why, so the visitor never gets a generic send failure.
   */
  let widgetUnavailable = false;
  /** AbortController for the in-flight turn (Stop-generation button). */
  let activeAbort: AbortController | null = null;
  /** Last question whose send failed (re-sent by the banner Retry action). */
  let lastFailedQuestion: string | null = null;
  let lastError: WidgetError | null = null;

  // --- Offline awareness (plan §9) -----------------------------------------

  const onConnectivityChange = (): void => syncRenderer();
  window.addEventListener('online', onConnectivityChange);
  window.addEventListener('offline', onConnectivityChange);

  // --- UI assembly ---------------------------------------------------------

  const style = document.createElement('style');
  style.textContent = WIDGET_STYLES;
  shadowRoot.appendChild(style);

  const shell = document.createElement('div');
  shell.className = 'wc-shell';
  shell.setAttribute('data-position', currentConfig.position);

  const launcher = createLauncher({
    position: currentConfig.position,
    isOpen: () => open,
    onToggle: (next) => (next ? controller.open() : controller.close()),
  });

  const messageList = createMessageList();

  const windowElement = createChatWindow({
    config: currentConfig,
    messagesElement: messageList,
    onSend: (question) => void send(question),
    onClose: () => controller.close(),
    onSuggested: (question) => void send(question),
    onRetry: () => {
      if (lastFailedQuestion) {
        void send(lastFailedQuestion);
      }
    },
    onDismiss: () => {
      lastFailedQuestion = null;
      lastError = null;
      windowElement.setBanner(null);
    },
    onStop: () => {
      if (conversation.getState().streaming) {
        activeAbort?.abort();
      }
    },
    isDisabled: () => conversation.getState().streaming || isOffline() || widgetUnavailable,
  });

  shell.appendChild(windowElement.element);
  shell.appendChild(launcher);
  shadowRoot.appendChild(shell);

  // --- Bubble actions (delegated: copy / retry / show-more) ----------------

  wireMessageActions(messageList, {
    onCopyCode(code: string): void {
      void copyText(code).then((ok) => announce(ok ? 'Code copied' : 'Copy failed'));
    },
    onRetry(messageId: string): void {
      retryMessage(messageId);
    },
    onToggleMore(messageId: string): void {
      const message = conversation.getState().messages.find((m) => m.id === messageId);
      if (message) {
        toggleExpanded(messageList, message);
      }
    },
    onFeedbackSubmit(messageId: string, payload: FeedbackSubmitPayload): void {
      void submitFeedbackFor(messageId, payload);
    },
  });

  // --- Send path -----------------------------------------------------------

  async function send(question: string) {
    if (conversation.getState().streaming || isOffline() || widgetUnavailable) {
      return;
    }
    windowElement.composer.reset();
    windowElement.setBanner(null);
    lastFailedQuestion = null;
    lastError = null;

    conversation.addUserMessage(question);
    const turnId = conversation.startAssistantTurn();

    const client = {
      getToken: () => session.ensureFresh(),
      reissueToken: () => session.reissue(),
    };

    const handlers = {
      onSources: (sources: ChatMessage['sources']) => {
        if (sources?.length) {
          conversation.setSources(turnId, sources);
        }
      },
      onDelta: (delta: string) => conversation.appendDelta(turnId, delta),
      onDone: (done: { session_id?: string; message_id?: string }) => {
        if (done.session_id) {
          conversation.setSessionId(done.session_id);
        }
        if (done.message_id) {
          conversation.setMessageId(turnId, done.message_id);
        }
        conversation.endTurn(turnId);
      },
      onError: (error: WidgetError) => {
        lastFailedQuestion = question;
        lastError = error;
        windowElement.setBanner(error.userMessage, error.retryable);
        conversation.failTurn(turnId, error.userMessage);
      },
    };

    const turn = new AbortController();
    activeAbort = turn;
    try {
      const result = await streamChat(
        { widgetId, apiBaseUrl },
        { question, sessionId: conversation.getState().sessionId },
        handlers,
        client,
        fetchImpl,
        turn.signal,
      );
      if (result.aborted) {
        // User pressed Stop: keep the partial answer, mark it stopped (not an
        // error), and never surface a failure banner.
        conversation.stopTurn(turnId);
      } else if (!result.completed && !result.error) {
        conversation.endTurn(turnId); // safety net
      }
    } finally {
      if (activeAbort === turn) {
        activeAbort = null;
      }
    }
    syncRenderer();
  }

  function retryMessage(messageId: string): void {
    const messages = conversation.getState().messages;
    const index = messages.findIndex((m) => m.id === messageId);
    if (index < 0) {
      return;
    }
    for (let i = index - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') {
        void send(messages[i].content);
        return;
      }
    }
  }

  // --- Feedback submission (Phase 12.4) -----------------------------------

  async function submitFeedbackFor(
    messageId: string,
    payload: FeedbackSubmitPayload,
  ): Promise<void> {
    const state = conversation.getState();
    const message = state.messages.find((m) => m.id === messageId);
    // A backend message id is required (bound from the SSE `done` event).
    if (!message?.messageId || !state.sessionId) {
      conversation.setFeedback(messageId, {
        status: 'error',
        rating: payload.rating,
        category: payload.category,
        comment: payload.comment,
      });
      return;
    }
    const feedback: FeedbackState = {
      status: 'submitting',
      rating: payload.rating,
      category: payload.category,
      comment: payload.comment,
    };
    conversation.setFeedback(messageId, feedback);
    try {
      await submitFeedback(
        { widgetId, apiBaseUrl },
        {
          sessionId: state.sessionId,
          messageId: message.messageId,
          rating: payload.rating,
          category: payload.category as 'helpful' | 'wrong' | 'incomplete' | 'offensive' | 'other',
          comment: payload.comment,
        },
        {
          getToken: () => session.ensureFresh(),
          reissueToken: () => session.reissue(),
        },
        fetchImpl,
      );
      conversation.setFeedback(messageId, { ...feedback, status: 'submitted' });
      announce('Feedback sent');
    } catch {
      conversation.setFeedback(messageId, { ...feedback, status: 'error' });
    }
  }

  // --- Rendering -----------------------------------------------------------

  let statusTimer: ReturnType<typeof setTimeout> | null = null;
  let currentStatus = '';

  function announce(text: string): void {
    currentStatus = text;
    windowElement.setStatus(text);
    if (statusTimer) {
      clearTimeout(statusTimer);
    }
    statusTimer = setTimeout(() => {
      if (currentStatus === text) {
        currentStatus = '';
        windowElement.setStatus('');
      }
    }, 2500);
  }

  function renderMessagesNow() {
    const messages = conversation.getState().messages;
    renderMessages(messageList, messages);
    if (messages.length === 0 && currentConfig.welcome_message) {
      messageList.appendChild(createWelcomeBubble(currentConfig.welcome_message));
    }
  }

  function syncRenderer() {
    const offline = isOffline();
    if (widgetUnavailable) {
      // Disabled/suspended widget: persistent banner, no chat. Takes priority
      // over the offline banner so the visitor knows the *why*.
      windowElement.setBanner(WIDGET_UNAVAILABLE_BANNER);
    } else if (offline) {
      windowElement.setBanner(OFFLINE_BANNER);
    } else if (windowElement.currentBanner() === OFFLINE_BANNER) {
      // Offline cleared: restore the pending error banner so Retry stays available.
      if (lastError) {
        windowElement.setBanner(lastError.userMessage, lastError.retryable);
      } else {
        windowElement.setBanner(null);
      }
    }

    const state = conversation.getState();
    renderMessagesNow();
    setBusy(messageList, state.streaming);
    windowElement.setStreaming(state.streaming);
    windowElement.composer.setDisabled(state.streaming || offline || widgetUnavailable);
    windowElement.element.hidden = !open;
    syncLauncher(launcher, open);
  }

  function applyConfig(config: WidgetPublicConfig) {
    currentConfig = config;
    applyTheme(host, config);
    shell.setAttribute('data-position', config.position);
    windowElement.element.setAttribute('data-position', config.position);
    windowElement.composer.input.placeholder = config.placeholder;
    windowElement.syncSuggested(config.suggested_questions);
    if (config.auto_open && !prefersReducedMotion()) {
      controller.open();
    }
  }

  const controller: WidgetController = {
    widgetId,
    apiBaseUrl,
    visitorId,
    session,
    getConfig() {
      return currentConfig;
    },
    ready() {
      if (configLoaded) {
        return Promise.resolve(currentConfig);
      }
      return new Promise<WidgetPublicConfig>((resolve) => {
        configWaiters.push(resolve);
      });
    },
    isOpen() {
      return open;
    },
    open() {
      if (destroyed) {
        return;
      }
      open = true;
      windowElement.trapFocus();
      launcher.tabIndex = -1; // out of the tab order while the dialog is open
      syncRenderer();
    },
    close() {
      if (!open) {
        return;
      }
      open = false;
      windowElement.releaseFocus();
      launcher.tabIndex = 0;
      syncRenderer();
      launcher.focus();
    },
    sendMessage(question: string) {
      void send(question);
    },
    destroy() {
      if (destroyed) {
        return;
      }
      destroyed = true;
      open = false;
      activeAbort?.abort();
      activeAbort = null;
      window.removeEventListener('online', onConnectivityChange);
      window.removeEventListener('offline', onConnectivityChange);
      windowElement.releaseFocus();
      shadowRoot.replaceChildren();
      host.remove();
    },
  };

  async function start() {
    const config = await loadConfig({ widgetId, apiBaseUrl }, fetchImpl, configStore);
    if (destroyed) {
      return;
    }
    // An explicit `enabled: false` from the backend (disabled widget or
    // suspended tenant) blocks chat up front; fetch failures keep the safe
    // defaults (enabled: true) so a transient config outage never bricks the
    // embed for a healthy widget.
    widgetUnavailable = !config.enabled;
    applyConfig(config);
    configLoaded = true;
    for (const waiter of configWaiters) {
      waiter(config);
    }
    configWaiters.length = 0;
    if (!widgetUnavailable) {
      // Ensure a session is ready up front so the first message never waits.
      try {
        await session.ensureFresh();
      } catch {
        // Session failures are surfaced on first send; the launcher still renders.
      }
    }
    syncRenderer();
  }

  defineWidgetElement();
  conversation.onChange = () => syncRenderer();
  syncRenderer();
  if (options.autoStart ?? true) {
    void start();
  }
  return controller;
}

function createHost(widgetId: string, apiBaseUrl: string): HTMLElement {
  const host = document.createElement(HOST_TAG);
  host.setAttribute('data-widget-id', widgetId);
  host.setAttribute('data-api-base-url', apiBaseUrl);
  document.body.appendChild(host);
  return host;
}
