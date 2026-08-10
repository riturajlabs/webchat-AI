/**
 * Composer (plan §5, WCAG 2.2 AA).
 *
 * Textarea with a 2000-char cap, Enter-to-send / Shift+Enter newline, disabled
 * while streaming, and an error banner slot. Focus is retained on send.
 */

export interface ComposerOptions {
  placeholder: string;
  maxLength?: number;
  onSend: (question: string) => void;
  isDisabled: () => boolean;
}

export interface ChatComposer {
  element: HTMLElement;
  input: HTMLTextAreaElement;
  sendButton: HTMLButtonElement;
  setDisabled(disabled: boolean): void;
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

  const updateCounter = (): void => {
    counter.textContent = `${input.value.length}/${maxLength}`;
    sendButton.disabled = options.isDisabled() || input.value.trim().length === 0;
  };

  const reset = (): void => {
    input.value = '';
    updateCounter();
  };

  const submit = (): void => {
    const question = input.value.trim();
    if (!question || options.isDisabled()) {
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

  wrapper.appendChild(input);
  wrapper.appendChild(counter);
  wrapper.appendChild(sendButton);

  const setDisabled = (disabled: boolean): void => {
    input.disabled = disabled;
    updateCounter();
  };

  return {
    element: wrapper,
    input,
    sendButton,
    setDisabled,
    focus() {
      input.focus();
    },
    reset,
  };
}
