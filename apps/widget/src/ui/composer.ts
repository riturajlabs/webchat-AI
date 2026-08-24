/**
 * Composer (plan §5, WCAG 2.2 AA).
 *
 * A rounded textarea with a 2000-char cap, Enter-to-send / Shift+Enter newline,
 * an icon send button (SVG paper-plane), and an IME-safe Enter guard (audit
 * W-13): Enter presses that confirm a CJK composition never send. While a real
 * SSE turn streams the Stop button replaces Send, but the input stays editable
 * (audit: composer lockout) and a question submitted mid-stream is queued and
 * sent automatically when the turn completes. While a local conversational
 * reply is "thinking" the Send button shows a small loading spinner instead.
 * Focus is retained on send.
 */

export interface ComposerOptions {
  placeholder: string;
  maxLength?: number;
  onSend: (question: string) => void;
  isDisabled: () => boolean;
  /** Called when the Stop-generation button is pressed (Phase 10). */
  onStop?: () => void;
}

export interface ChatComposer {
  element: HTMLElement;
  input: HTMLTextAreaElement;
  sendButton: HTMLButtonElement;
  /** Stop-generation button; hidden unless a turn streams. */
  stopButton: HTMLButtonElement;
  setDisabled(disabled: boolean): void;
  /**
   * Swap Send ↔ Stop while a real stream is in flight. The input stays
   * editable so the visitor can pre-type the next question (audit: composer
   * lockout); submitting mid-stream queues it for auto-send on completion.
   */
  setStreaming(streaming: boolean): void;
  /** Show the send-button loading spinner while a reply is pending. */
  setBusy(busy: boolean): void;
  focus(): void;
  reset(): void;
}

export const COMPOSER_MAX_LENGTH = 2000;

function sendIcon(): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '18');
  svg.setAttribute('height', '18');
  svg.setAttribute('fill', 'currentColor');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M2.01 21 23 12 2.01 3 2 10l15 2-15 2z');
  svg.appendChild(path);
  return svg;
}

function stopIcon(): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '14');
  svg.setAttribute('height', '14');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  rect.setAttribute('x', '6');
  rect.setAttribute('y', '6');
  rect.setAttribute('width', '12');
  rect.setAttribute('height', '12');
  rect.setAttribute('rx', '2');
  rect.setAttribute('fill', 'currentColor');
  svg.appendChild(rect);
  return svg;
}

export function createComposer(options: ComposerOptions): ChatComposer {
  const maxLength = options.maxLength ?? COMPOSER_MAX_LENGTH;

  const wrapper = document.createElement('div');
  wrapper.className = 'wc-composer';

  // Compact pill: input + send/stop share one rounded container (Phase 12).
  const pill = document.createElement('div');
  pill.className = 'wc-composer-pill';

  const input = document.createElement('textarea');
  input.className = 'wc-composer-input';
  input.placeholder = options.placeholder;
  input.setAttribute('rows', '1');
  input.setAttribute('maxlength', String(maxLength));
  input.setAttribute('aria-label', 'Message the assistant');

  const sendButton = document.createElement('button');
  sendButton.type = 'button';
  sendButton.className = 'wc-send';
  sendButton.setAttribute('aria-label', 'Send message');
  sendButton.appendChild(sendIcon());
  sendButton.disabled = true;

  const spinner = document.createElement('span');
  spinner.className = 'wc-send-spinner';
  spinner.setAttribute('aria-hidden', 'true');

  const stopButton = document.createElement('button');
  stopButton.type = 'button';
  stopButton.className = 'wc-stop';
  stopButton.setAttribute('aria-label', 'Stop generating');
  stopButton.appendChild(stopIcon());
  stopButton.hidden = true;

  let locked = false;
  let streaming = false;
  /** Next question typed while a turn streams; auto-sent when it completes. */
  let pendingQuestion: string | null = null;

  /** Grow the textarea with its content, up to the CSS max-height. */
  const autogrow = (): void => {
    // jsdom (and collapsed layouts) report scrollHeight 0; skip so the
    // inline height never collapses the field.
    if (input.scrollHeight > 0) {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 88)}px`;
    }
  };

  const updateSend = (): void => {
    sendButton.disabled = locked || options.isDisabled() || input.value.trim().length === 0;
  };

  const reset = (): void => {
    input.value = '';
    input.style.height = '';
    updateSend();
  };

  const submit = (): void => {
    const question = input.value.trim();
    if (!question || locked) {
      return;
    }
    if (streaming) {
      // Audit (composer lockout): the visitor can keep typing during a turn.
      // Buffer the draft and send it the moment the stream completes instead
      // of dropping it (the outer send path is gated while streaming).
      pendingQuestion = question;
      input.value = '';
      input.style.height = '';
      updateSend();
      return;
    }
    if (options.isDisabled()) {
      return;
    }
    options.onSend(question);
    reset();
  };

  input.addEventListener('input', () => {
    autogrow();
    updateSend();
  });
  input.addEventListener('keydown', (event: KeyboardEvent) => {
    // Audit W-13: Enter that confirms an IME composition (CJK input, or the
    // legacy keyCode 229 signal) must never trigger submit — it belongs to
    // the composition itself and must not be swallowed either.
    if (event.isComposing || event.keyCode === 229) {
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });
  sendButton.addEventListener('click', submit);
  stopButton.addEventListener('click', () => options.onStop?.());

  pill.appendChild(input);
  pill.appendChild(sendButton);
  pill.appendChild(spinner);
  pill.appendChild(stopButton);
  wrapper.appendChild(pill);

  const setDisabled = (disabled: boolean): void => {
    locked = disabled;
    input.disabled = disabled;
    updateSend();
  };

  const setStreaming = (next: boolean): void => {
    if (next === streaming) {
      return;
    }
    const stopWasFocused = document.activeElement === stopButton;
    streaming = next;
    sendButton.hidden = next;
    stopButton.hidden = !next;
    updateSend();
    if (next) {
      stopButton.focus();
    } else {
      if (stopWasFocused) {
        // The Stop button just left the DOM-visible state (which would drop
        // focus to <body>); keep it inside the composer instead.
        input.focus();
      }
      // Audit (composer lockout): deliver a question queued mid-stream now
      // that the turn has finished and the send path is unblocked again.
      if (pendingQuestion) {
        const queued = pendingQuestion;
        pendingQuestion = null;
        options.onSend(queued);
      }
    }
  };

  const setBusy = (busy: boolean): void => {
    wrapper.classList.toggle('wc-busy', busy);
  };

  return {
    element: wrapper,
    input,
    sendButton,
    stopButton,
    setDisabled,
    setStreaming,
    setBusy,
    focus() {
      input.focus();
    },
    reset,
  };
}
