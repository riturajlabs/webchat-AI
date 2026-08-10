/**
 * Composer (plan §5, WCAG 2.2 AA).
 *
 * Textarea with a 2000-char cap, Enter-to-send / Shift+Enter newline, disabled
 * while streaming, and an error banner slot. Focus is retained on send.
 *
 * Phase 10: a Stop button (`.wc-stop`) replaces the Send button while the
 * assistant turn is streaming; clicking it calls `onStop`. `setStreaming`
 * drives that swap and keeps the input disabled mid-turn so a second message
 * can't be sent before the first finishes.
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
  /** Stop-generation button; hidden unless a turn is streaming. */
  stopButton: HTMLButtonElement;
  setDisabled(disabled: boolean): void;
  /** Swap Send ↔ Stop and lock the input while a turn streams. */
  setStreaming(streaming: boolean): void;
  focus(): void;
  reset(): void;
}

export const COMPOSER_MAX_LENGTH = 2000;

export function createComposer(options: ComposerOptions): ChatComposer {
  const maxLength = options.maxLength ?? COMPOSER_MAX_LENGTH;

  const wrapper = document.createElement('div');
  wrapper.className = 'wc-composer';

  const input = document.createElement('textarea');
  input.className = 'wc-composer-input';
  input.placeholder = options.placeholder;
  input.setAttribute('rows', '1');
  input.setAttribute('maxlength', String(maxLength));
  input.setAttribute('aria-label', 'Message the assistant');

  const counter = document.createElement('span');
  counter.className = 'wc-counter';
  counter.setAttribute('aria-hidden', 'true');

  const sendButton = document.createElement('button');
  sendButton.type = 'button';
  sendButton.className = 'wc-send';
  sendButton.setAttribute('aria-label', 'Send message');
  sendButton.textContent = 'Send';
  sendButton.disabled = true;

  const stopButton = document.createElement('button');
  stopButton.type = 'button';
  stopButton.className = 'wc-stop';
  stopButton.setAttribute('aria-label', 'Stop generating');
  stopButton.textContent = 'Stop';
  stopButton.hidden = true;

  let locked = false;
  let streaming = false;

  const updateCounter = (): void => {
    counter.textContent = `${input.value.length}/${maxLength}`;
    sendButton.disabled = locked || options.isDisabled() || input.value.trim().length === 0;
  };

  const reset = (): void => {
    input.value = '';
    updateCounter();
  };

  const submit = (): void => {
    const question = input.value.trim();
    if (!question || locked || options.isDisabled()) {
      return;
    }
    options.onSend(question);
    reset();
  };

  input.addEventListener('input', updateCounter);
  input.addEventListener('keydown', (event: KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });
  sendButton.addEventListener('click', submit);
  stopButton.addEventListener('click', () => options.onStop?.());

  wrapper.appendChild(input);
  wrapper.appendChild(counter);
  wrapper.appendChild(sendButton);
  wrapper.appendChild(stopButton);

  const setDisabled = (disabled: boolean): void => {
    locked = disabled;
    input.disabled = disabled;
    updateCounter();
  };

  const setStreaming = (next: boolean): void => {
    if (next === streaming) {
      return;
    }
    streaming = next;
    input.disabled = next;
    sendButton.hidden = next;
    stopButton.hidden = !next;
    if (next) {
      stopButton.focus();
    }
  };

  return {
    element: wrapper,
    input,
    sendButton,
    stopButton,
    setDisabled,
    setStreaming,
    focus() {
      input.focus();
    },
    reset,
  };
}
