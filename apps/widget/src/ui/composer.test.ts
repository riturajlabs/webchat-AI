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

  it('setStreaming swaps Send for Stop but keeps the input editable', () => {
    const { composer } = setup();
    composer.setStreaming(true);
    expect(composer.sendButton.hidden).toBe(true);
    expect(composer.stopButton.hidden).toBe(false);
    // Audit (composer lockout): the visitor can pre-type while a turn streams.
    expect(composer.input.disabled).toBe(false);
    expect(document.activeElement).toBe(composer.stopButton);

    composer.setStreaming(false);
    expect(composer.sendButton.hidden).toBe(false);
    expect(composer.stopButton.hidden).toBe(true);
    expect(document.activeElement).toBe(composer.input);
  });

  it('ignores Enter that confirms an IME composition without swallowing it (W-13)', () => {
    const { composer, onSend } = setup();
    composer.input.value = 'こん';
    const composing = new KeyboardEvent('keydown', {
      key: 'Enter',
      isComposing: true,
      bubbles: true,
    });
    const preventDefault = vi.spyOn(composing, 'preventDefault');
    composer.input.dispatchEvent(composing);
    // The keypress belongs to the composition: not sent, and not prevented
    // either (preventing it would break the candidate confirmation).
    expect(onSend).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });

  it('ignores legacy keyCode 229 composition Enter (W-13)', () => {
    const { composer, onSend } = setup();
    composer.input.value = 'ni hao';
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
    Object.defineProperty(event, 'keyCode', { value: 229 });
    composer.input.dispatchEvent(event);
    expect(onSend).not.toHaveBeenCalled();

    // A real Enter (keyCode 13) still sends.
    const real = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });
    Object.defineProperty(real, 'keyCode', { value: 13 });
    composer.input.dispatchEvent(real);
    expect(onSend).toHaveBeenCalledWith('ni hao');
  });

  it('queues a question submitted mid-stream and auto-sends it when the turn completes', () => {
    const { composer, onSend } = setup();
    composer.setStreaming(true);

    composer.input.value = 'next question';
    composer.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    // Buffered, not dropped and not sent into the active stream.
    expect(onSend).not.toHaveBeenCalled();
    expect(composer.input.value).toBe('');

    composer.setStreaming(false);
    expect(onSend).toHaveBeenCalledWith('next question');
  });

  it('queues each draft and sends them in order when the turn completes', () => {
    const { composer, onSend } = setup();
    composer.setStreaming(true);

    composer.input.value = 'first draft';
    composer.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    composer.input.value = 'second draft';
    composer.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

    // First completion drains the oldest queued draft.
    composer.setStreaming(false);
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenNthCalledWith(1, 'first draft');

    // Simulate the stream cycle: onSend starts a new stream, which ends and
    // drains the next queued draft.
    composer.setStreaming(true);
    composer.setStreaming(false);
    expect(onSend).toHaveBeenCalledTimes(2);
    expect(onSend).toHaveBeenNthCalledWith(2, 'second draft');
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
