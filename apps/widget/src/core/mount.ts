/**
 * Widget lifecycle (plan §5.1, ADR-004).
 *
 * `mount()` attaches a **closed** shadow root to the host `<webchat-widget>`
 * element, wires the core services (visitor identity, session tokens, config)
 * and renders the UI (launcher + chat window) into the shadow root. The theme
 * is applied via CSS custom properties on the host element.
 */

import { loadConfig, type ConfigStore } from '../config/fetch';
import { defaultConfig, type WidgetOptions, type WidgetPublicConfig } from '../config/types';
import { SessionManager } from './session';
import { getVisitorId } from './visitor';
import { isOffline } from './network';
import { applyTheme, prefersReducedMotion } from '../theme/apply';
import { createLauncher, syncLauncher } from '../ui/launcher';
import { createChatWindow } from '../ui/window';
import { createMessageList, createWelcomeBubble, renderMessages, setBusy } from '../ui/bubbles';
import { WIDGET_STYLES } from '../ui/styles';
import { streamChat } from '../stream/client';
import { Conversation } from '../stream/chat';
import type { WidgetError } from './errors';

/** Banner shown while the browser reports itself offline (plan §9). */
export const OFFLINE_BANNER = "You're offline. Messages will be sent once your connection returns.";

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

/**
 * Mount the widget into `host` (or a fresh `<webchat-widget>` appended to the
 * document body) and return a controller.
 */
export function mount(options: WidgetHostOptions): WidgetController {
  const widgetId = options.widgetId;
  const apiBaseUrl = options.apiBaseUrl ?? '/api/widget/v1';
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
    isDisabled: () => conversation.getState().streaming || isOffline(),
  });

  shell.appendChild(windowElement.element);
  shell.appendChild(launcher);
  shadowRoot.appendChild(shell);

  // --- Send path -----------------------------------------------------------

  async function send(question: string) {
    if (conversation.getState().streaming || isOffline()) {
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
      onDelta: (delta: string) => conversation.appendDelta(turnId, delta),
      onDone: (done: { session_id?: string }) => {
        if (done.session_id) {
          conversation.setSessionId(done.session_id);
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

    await streamChat(
      { widgetId, apiBaseUrl },
      { question, sessionId: conversation.getState().sessionId },
      handlers,
      client,
      fetchImpl,
    );

    conversation.endTurn(turnId);
    syncRenderer();
  }

  // --- Rendering -----------------------------------------------------------

  function renderMessagesNow() {
    const messages = conversation.getState().messages;
    renderMessages(messageList, messages);
    if (messages.length === 0 && currentConfig.welcome_message) {
      messageList.appendChild(createWelcomeBubble(currentConfig.welcome_message));
    }
  }

  function syncRenderer() {
    const offline = isOffline();
    if (offline) {
      windowElement.setBanner(OFFLINE_BANNER);
    } else if (windowElement.currentBanner() === OFFLINE_BANNER) {
      // Offline cleared: restore the pending error banner so Retry stays available.
      if (lastError) {
        windowElement.setBanner(lastError.userMessage, lastError.retryable);
      } else {
        windowElement.setBanner(null);
      }
    }
    renderMessagesNow();
    setBusy(messageList, conversation.getState().streaming);
    windowElement.composer.setDisabled(conversation.getState().streaming || offline);
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
    destroy() {
      if (destroyed) {
        return;
      }
      destroyed = true;
      open = false;
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
    applyConfig(config);
    configLoaded = true;
    for (const waiter of configWaiters) {
      waiter(config);
    }
    configWaiters.length = 0;
    // Ensure a session is ready up front so the first message never waits.
    try {
      await session.ensureFresh();
    } catch {
      // Session failures are surfaced on first send; the launcher still renders.
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
