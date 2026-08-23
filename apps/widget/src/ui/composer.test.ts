import { describe, expect, it, vi } from 'vitest';
import { createComposer, COMPOSER_MAX_LENGTH } from './composer';

function setup() {
  const onSend = vi.fn();
  const composer = createComposer({
    placeholder: 'Ask…',
    onSend,
    isDisabled: () => false,
  });
  document.body.appendChild(composer.element);
  return { composer, onSend };
}

describe('createComposer', () => {
  it('sends trimmed non-empty input and resets', () => {
    const { composer, onSend } = setup();
    composer.input.value = '  hello  ';
    composer.input.dispatchEvent(new Event('input'));
    composer.sendButton.click();
    expect(onSend).toHaveBeenCalledWith('hello');
    expect(composer.input.value).toBe('');
  });

  it('does not send empty input', () => {
    const { composer, onSend } = setup();
    composer.sendButton.click();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('sends on Enter but not Shift+Enter', () => {
    const { composer, onSend } = setup();
    composer.input.value = 'question';
    const enter = new KeyboardEvent('keydown', { key: 'Enter' });
    composer.input.dispatchEvent(enter);
    expect(onSend).toHaveBeenCalledWith('question');

    const { composer: composer2, onSend: onSend2 } = setup();
    composer2.input.value = 'line1';
    const shiftEnter = new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true });
    composer2.input.dispatchEvent(shiftEnter);
    expect(onSend2).not.toHaveBeenCalled();
  });

  it('caps input at the max length attribute', () => {
    const { composer } = setup();
    expect(composer.input.maxLength).toBe(COMPOSER_MAX_LENGTH);
  });

  it('setDisabled disables the input and send', () => {
    const { composer } = setup();
    composer.setDisabled(true);
    expect(composer.input.disabled).toBe(true);
    expect(composer.sendButton.disabled).toBe(true);
  });

  it('keeps the Stop button hidden until a turn streams', () => {
    const { composer } = setup();
    expect(composer.stopButton.hidden).toBe(true);
    expect(composer.sendButton.hidden).toBe(false);
  });

  it('setStreaming swaps Send for Stop and disables the input', () => {
    const { composer } = setup();
    composer.setStreaming(true);
    expect(composer.sendButton.hidden).toBe(true);
    expect(composer.stopButton.hidden).toBe(false);
    expect(composer.input.disabled).toBe(true);
    expect(document.activeElement).toBe(composer.stopButton);

    composer.setStreaming(false);
    expect(composer.sendButton.hidden).toBe(false);
    expect(composer.stopButton.hidden).toBe(true);
    expect(composer.input.disabled).toBe(false);
  });

  it('returns focus to the input when streaming ends while Stop is focused', () => {
    const { composer } = setup();
    composer.setStreaming(true);
    expect(document.activeElement).toBe(composer.stopButton);
    composer.setStreaming(false);
    // Focus must not fall out of the composer to <body> when Stop disappears.
    expect(document.activeElement).toBe(composer.input);
  });

  it('clears the auto-grow height on reset', () => {
    const { composer } = setup();
    composer.input.style.height = '88px';
    composer.input.value = 'hello';
    composer.input.dispatchEvent(new Event('input'));
    composer.sendButton.click();
    expect(composer.input.value).toBe('');
    expect(composer.input.style.height).toBe('');
  });

  it('calls onStop when the Stop button is pressed', () => {
    const onStop = vi.fn();
    const composer = createComposer({
      placeholder: 'Ask…',
      onSend: () => {},
      isDisabled: () => false,
      onStop,
    });
    composer.stopButton.click();
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});
