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
import { applyTheme, prefersReducedMotion, wireSystemThemeChange } from '../theme/apply';
import { createLauncher, syncLauncher } from '../ui/launcher';
import { createChatWindow } from '../ui/window';
import {
  createEmptyState,
  createMessageList,
  renderMessages,
  setBusy,
  toggleExpanded,
  wireMessageActions,
} from '../ui/bubbles';
import { submitFeedback } from '../feedback/api';
import type { FeedbackSubmitPayload } from '../ui/feedback';
import type { FeedbackState } from '../stream/chat';
import { wireKeyboardInset } from '../ui/viewport';
import { WIDGET_STYLES } from '../ui/styles';
import { streamChat } from '../stream/client';
import { Conversation, type ChatMessage } from '../stream/chat';
import { WidgetError } from './errors';
import {
  detectIntent,
  isNoContextAnswer,
  NO_CONTEXT_ANSWER,
  NO_CONTEXT_REPLY,
} from '../conversation/intent';

/** Banner shown while the browser reports itself offline (plan §9). */
export const OFFLINE_BANNER = "You're offline. Reconnect to send messages.";

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
  /**
   * Delay before a local conversational reply (greeting/thanks/farewell)
   * appears, giving the "AI is typing" indicator a moment to show. Test seam.
   */
  intentReplyDelayMs?: number;
}

/** How long the "AI is typing" indicator shows before a conversational reply. */
export const INTENT_REPLY_DELAY_MS = 700;

/**
 * Per-turn latency profiling (Phase 12). Logs time-to-first-token and total
 * turn duration via `console.debug` (silent unless the embed/page enables
 * debug logging), including the backend's own timing breakdown when the SSE
 * `done` event carries it (`perf_timing_log_enabled`).
 */
export function profileTurn(widgetId: string) {
  const start = performance.now();
  let firstTokenLogged = false;
  return {
    markFirstToken(): void {
      if (firstTokenLogged) {
        return;
      }
      firstTokenLogged = true;
      console.debug(
        `[webchat:${widgetId}] first token in ${Math.round(performance.now() - start)}ms`,
      );
    },
    complete(timing?: {
      embedding_ms?: number;
      retrieval_ms?: number;
      generation_ms?: number;
      total_ms?: number;
    }): void {
      const elapsed = Math.round(performance.now() - start);
      const backend = timing?.total_ms != null ? `, backend total ${timing.total_ms}ms` : '';
      const parts = ['embedding', 'retrieval', 'generation']
        .filter(
          (phase) =>
            timing && (timing as Record<string, number | undefined>)[`${phase}_ms`] != null,
        )
        .map(
          (phase) => `${phase} ${(timing as Record<string, number | undefined>)[`${phase}_ms`]}ms`,
        )
        .join(', ');
      console.debug(
        `[webchat:${widgetId}] turn complete in ${elapsed}ms${backend}${parts ? ` (${parts})` : ''}`,
      );
    },
  };
}

/**
 * Surface the correlation id of a failed turn via `console.debug` (Phase 2
 * tracing): the id joins the widget's error report with the backend logs for
 * the exact request (`X-Request-ID`). Silent unless debug logging is enabled.
 */
export function reportTurnErrorId(widgetId: string, error: WidgetError): void {
  if (!error.requestId) {
    return;
  }
  console.debug(`[webchat:${widgetId}] turn failed (request_id=${error.requestId})`);
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

/**
 * Hosts already mounted via `mount()`. Mounting the same element again (a
 * double-init or a repeated `autoUpgrade`) returns the existing controller
 * instead of attaching a second UI shell (multi-embed guard).
 */
const mountedHosts = new WeakMap<HTMLElement, WidgetController>();

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
 * document body) and return a controller. Re-mounting the same host is
 * idempotent: the existing controller is returned and no duplicate UI is
 * attached.
 */
export function mount(options: WidgetHostOptions): WidgetController {
  const widgetId = options.widgetId;
  const apiBaseUrl = resolveApiBaseUrl(options.apiBaseUrl);
  const fetchImpl = options.fetchImpl ?? fetch;
  const configStore = options.configStore;

  const host = options.host ?? createHost(widgetId, apiBaseUrl);
  const existing = mountedHosts.get(host);
  if (existing) {
    return existing;
  }
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
  /**
   * Turn id of the most recent real SSE stream. When it completes, its final
   * answer is pushed into the status live region (audit W-12): the streaming
   * bubble mutates via innerHTML, which `aria-relevant="additions"` never
   * announces — without this, screen-reader users hear "typing" then silence.
   */
  let lastStreamedTurnId: string | null = null;
  /**
   * Banner condition the visitor explicitly dismissed (audit W-02). A dismissal
   * suppresses only that exact, continuously-persisting condition: syncRenderer
   * re-runs on every state change and used to resurrect dismissed banners on
   * each pass. The flag expires as soon as the underlying condition changes or
   * clears, and a new send resets it.
   */
  let bannerDismissedFor: string | null = null;

  /** The current banner-worthy condition, or null when things are fine. */
  function currentBannerCause(): { key: string; message: string; retryable: boolean } | null {
    if (widgetUnavailable) {
      return { key: 'unavailable', message: WIDGET_UNAVAILABLE_BANNER, retryable: false };
    }
    if (isOffline()) {
      return { key: 'offline', message: OFFLINE_BANNER, retryable: false };
    }
    if (lastError) {
      return {
        key: `error:${lastError.userMessage}`,
        message: lastError.userMessage,
        retryable: lastError.retryable,
      };
    }
    return null;
  }

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
    onSend: (question) => void send(question).catch(() => {}),
    onClose: () => controller.close(),
    onSuggested: (question) => void send(question).catch(() => {}),
    onRetry: () => {
      if (lastFailedQuestion) {
        void send(lastFailedQuestion).catch(() => {});
      }
    },
    onDismiss: () => {
      // Audit W-02: remember *which* condition was dismissed so syncRenderer
      // passes stop resurrecting the banner; genuinely new conditions (a new
      // error message, an offline episode) still surface.
      bannerDismissedFor = currentBannerCause()?.key ?? null;
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

  // --- Mobile keyboard inset (audit W-06) -----------------------------------
  // Mirrors the keyboard-occluded height into --wc-keyboard-inset on the shell
  // so the styles can lift/shrink the window above an on-screen keyboard.

  const detachKeyboardInset = wireKeyboardInset(window.visualViewport ?? null, shell);

  // --- OS theme changes (audit W-03) -----------------------------------------
  // theme:'auto' used to be evaluated once at mount; this keeps the resolved
  // palette in sync when the visitor flips their system light/dark preference.

  const detachSystemTheme = wireSystemThemeChange(host, () => currentConfig);

  // --- Bubble actions (delegated: copy / retry / show-more) ----------------
  // Phase 12: store the disposer so destroy() removes the event listener.

  const disposeMessageActions = wireMessageActions(messageList, {
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

  /**
   * Local conversational replies (greeting/thanks/farewell) never touch the
   * chat API: they are classified up front, shown through the same assistant
   * bubble (with the typing indicator for a short, natural delay) and complete
   * locally.
   */
  function respondWithIntent(reply: string): void {
    const turnId = conversation.startThinkingTurn();
    window.setTimeout(() => {
      if (destroyed) {
        return;
      }
      conversation.completeAssistantTurn(turnId, reply);
      syncRenderer();
    }, options.intentReplyDelayMs ?? INTENT_REPLY_DELAY_MS);
  }

  async function send(question: string) {
    if (conversation.getState().streaming || isOffline() || widgetUnavailable) {
      return;
    }
    windowElement.composer.reset();
    windowElement.setBanner(null);
    lastFailedQuestion = null;
    lastError = null;
    // A fresh attempt re-arms the banner: a visitor who retries deserves to
    // see the outcome even if they dismissed an identical failure before.
    bannerDismissedFor = null;

    conversation.addUserMessage(question);

    // Intent classification runs BEFORE RAG retrieval.
    const intent = detectIntent(question);
    if (intent) {
      respondWithIntent(intent.reply);
      return;
    }

    const turnId = conversation.startAssistantTurn();
    lastStreamedTurnId = turnId;
    const profiler = profileTurn(widgetId);

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
      onDelta: (delta: string) => {
        profiler.markFirstToken();
        // The backend streams its zero-context fallback as one delta; rewrite
        // it into the friendlier prompt before it ever renders. A model-side
        // fallback in multiple deltas is caught by the `done.fallback` guard.
        const current =
          conversation.getState().messages.find((m) => m.id === turnId)?.content ?? '';
        if (current === '' && delta === NO_CONTEXT_ANSWER) {
          conversation.appendDelta(turnId, NO_CONTEXT_REPLY);
        } else {
          conversation.appendDelta(turnId, delta);
        }
      },
      onDone: (done: {
        session_id?: string;
        message_id?: string;
        fallback?: unknown;
        timing?: {
          embedding_ms?: number;
          retrieval_ms?: number;
          generation_ms?: number;
          total_ms?: number;
        };
      }) => {
        profiler.complete(done.timing);
        if (done.session_id) {
          conversation.setSessionId(done.session_id);
        }
        if (done.message_id) {
          conversation.setMessageId(turnId, done.message_id);
        }
        if (done.fallback) {
          const message = conversation.getState().messages.find((m) => m.id === turnId);
          if (message && isNoContextAnswer(message.content)) {
            conversation.setAssistantContent(turnId, NO_CONTEXT_REPLY);
          }
        }
        conversation.endTurn(turnId);
      },
      onError: (error: WidgetError) => {
        lastFailedQuestion = question;
        lastError = error;
        reportTurnErrorId(widgetId, error);
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
    } catch (cause) {
      // streamChat rethrows non-abort failures that escape its internal
      // handling (e.g. the SSE body erroring mid-read). Without this catch
      // the turn would stay stuck in the streaming state and the rejection
      // would go unhandled.
      if (turn.signal.aborted) {
        conversation.stopTurn(turnId);
      } else {
        const error =
          cause instanceof WidgetError
            ? cause
            : new WidgetError({ code: 'network', message: 'Chat stream failed', cause });
        lastFailedQuestion = question;
        lastError = error;
        reportTurnErrorId(widgetId, error);
        windowElement.setBanner(error.userMessage, error.retryable);
        conversation.failTurn(turnId, error.userMessage);
      }
    } finally {
      if (activeAbort === turn) {
        activeAbort = null;
      }
    }
    try {
      syncRenderer();
    } catch {
      // Render errors must not crash the widget or go unhandled.
    }
  }

  function retryMessage(messageId: string): void {
    const messages = conversation.getState().messages;
    const index = messages.findIndex((m) => m.id === messageId);
    if (index < 0) {
      return;
    }
    for (let i = index - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') {
        void send(messages[i].content).catch(() => {});
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
      if (destroyed || currentStatus !== text) {
        return;
      }
      currentStatus = '';
      windowElement.setStatus('');
    }, 2500);
  }

  function renderMessagesNow() {
    const messages = conversation.getState().messages;
    renderMessages(messageList, messages);
    if (messages.length === 0) {
      messageList.replaceChildren(createEmptyState(currentConfig));
    }
  }

  let prevStreaming = false;
  /**
   * Last conversation revision already rendered into the message list. The
   * bubble reconciliation (`renderMessages`) is cheap per-change, but every
   * `syncRenderer` pass would otherwise re-scan the whole list; gating on the
   * revision skips that work for purely visual syncs (open/close, offline).
   */
  let lastRenderedRevision = -1;

  function syncRenderer() {
    const offline = isOffline();
    // Audit W-02: banner lifecycle is keyed to the underlying condition. A
    // dismissed condition stays dismissed for exactly as long as it persists;
    // changed/cleared conditions expire the dismissal so nothing stale is
    // suppressed and nothing dismissed resurrects.
    const cause = currentBannerCause();
    if (bannerDismissedFor && (!cause || cause.key !== bannerDismissedFor)) {
      bannerDismissedFor = null;
    }
    if (!cause || cause.key === bannerDismissedFor) {
      windowElement.setBanner(null);
    } else {
      windowElement.setBanner(cause.message, cause.retryable);
    }

    const state = conversation.getState();
    if (state.revision !== lastRenderedRevision) {
      renderMessagesNow();
      lastRenderedRevision = state.revision;
    }
    setBusy(messageList, state.streaming);
    // Stop appears only for backend turns; "thinking" turns (greetings etc.)
    // keep the Send button and show the spinner instead.
    windowElement.setStreaming(state.streaming && state.stoppable);
    windowElement.composer.setBusy(state.streaming && !state.stoppable);
    // Audit (composer lockout): the input stays editable while a turn streams
    // so the visitor can pre-type; it is hard-disabled only when sending is
    // genuinely impossible (offline / widget unavailable).
    windowElement.composer.setDisabled(offline || widgetUnavailable);
    windowElement.suggested.hidden = state.messages.some((m) => m.role === 'user');
    if (state.streaming && !prevStreaming) {
      windowElement.setStatus('AI is typing');
    } else if (!state.streaming && prevStreaming) {
      const last = state.messages[state.messages.length - 1];
      if (last && last.id === lastStreamedTurnId && !last.error && Boolean(last.content)) {
        // Audit W-12: announce the completed answer (kept partial answers
        // after Stop included); failed turns are announced by the alert banner.
        announce(last.content);
        lastStreamedTurnId = null;
      } else {
        windowElement.setStatus('');
      }
    }
    prevStreaming = state.streaming;
    shell.setAttribute('data-open', String(open));
    syncLauncher(launcher, open);
  }

  function applyConfig(config: WidgetPublicConfig) {
    currentConfig = config;
    applyTheme(host, config);
    shell.setAttribute('data-position', config.position);
    windowElement.element.setAttribute('data-position', config.position);
    windowElement.syncConfig(config);
    windowElement.syncSuggested(config.suggested_questions);
    // Force the message list to re-render: the empty state / welcome bubble
    // are built from the config.
    lastRenderedRevision = -1;
    // Audit W-04: auto_open is a functional request ("show the dialog"), not
    // motion — reduced-motion only disables the entrance animation (CSS), it
    // must not suppress the dialog itself.
    if (config.auto_open) {
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
      const element = windowElement.element;
      element.classList.remove('wc-closing');
      element.hidden = false;
      windowElement.trapFocus();
      launcher.tabIndex = -1; // out of the tab order while the dialog is open
      syncRenderer();
      messageList.scrollTop = messageList.scrollHeight;
    },
    close() {
      if (!open) {
        return;
      }
      const element = windowElement.element;
      if (prefersReducedMotion()) {
        open = false;
        windowElement.releaseFocus();
        launcher.tabIndex = 0;
        element.classList.remove('wc-closing');
        element.hidden = true;
        syncRenderer();
        launcher.focus();
        return;
      }
      // Play the close animation, then hide. The guard (`!open`) ignores the
      // timeout if the visitor reopens mid-animation.
      element.classList.add('wc-closing');
      window.setTimeout(() => {
        if (!open) {
          return;
        }
        open = false;
        windowElement.releaseFocus();
        launcher.tabIndex = 0;
        element.classList.remove('wc-closing');
        element.hidden = true;
        syncRenderer();
        launcher.focus();
      }, 180);
    },
    sendMessage(question: string) {
      const trimmed = question.trim();
      if (!trimmed) return;
      // Respect the composer's character limit for programmatic sends too.
      const limited = trimmed.length > 2000 ? trimmed.slice(0, 2000) : trimmed;
      void send(limited).catch(() => {
        // Synchronous throw before send's internal try/catch; already surfaced
        // via banner in the error handler. Prevents unhandled promise rejection.
      });
    },
    destroy() {
      if (destroyed) {
        return;
      }
      destroyed = true;
      open = false;
      activeAbort?.abort();
      activeAbort = null;
      detachKeyboardInset();
      detachSystemTheme();
      disposeMessageActions();
      if (statusTimer) {
        clearTimeout(statusTimer);
        statusTimer = null;
      }
      window.removeEventListener('online', onConnectivityChange);
      window.removeEventListener('offline', onConnectivityChange);
      windowElement.releaseFocus();
      shadowRoot.replaceChildren();
      mountedHosts.delete(host);
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

  /**
   * Streaming renders are coalesced to one render per animation frame
   * (production hardening): each SSE delta bumps the conversation revision,
   * and re-parsing the full markdown of the growing answer on every token is
   * O(n²) over a long reply. Coalescing keeps the stream visually identical
   * while capping DOM/markdown work at frame rate. Terminal transitions pay
   * at most one frame of delay (<16ms, imperceptible).
   */
  let renderScheduled = false;
  const scheduleFrame: (cb: () => void) => void =
    typeof window.requestAnimationFrame === 'function'
      ? (cb) => window.requestAnimationFrame(() => cb())
      : (cb) => window.setTimeout(cb, 16);

  function scheduleRender(): void {
    if (renderScheduled || destroyed) {
      return;
    }
    renderScheduled = true;
    scheduleFrame(() => {
      renderScheduled = false;
      if (!destroyed) {
        syncRenderer();
      }
    });
  }

  conversation.onChange = () => scheduleRender();
  syncRenderer();
  if (options.autoStart ?? true) {
    void start();
  }
  mountedHosts.set(host, controller);
  return controller;
}

function createHost(widgetId: string, apiBaseUrl: string): HTMLElement {
  const host = document.createElement(HOST_TAG);
  host.setAttribute('data-widget-id', widgetId);
  host.setAttribute('data-api-base-url', apiBaseUrl);
  document.body.appendChild(host);
  return host;
}
