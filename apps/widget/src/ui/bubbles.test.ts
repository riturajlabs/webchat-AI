import { describe, expect, it } from 'vitest';
import {
  appendMessage,
  createBubble,
  createMessageList,
  createWelcomeBubble,
  renderMessages,
  setBusy,
} from './bubbles';
import type { ChatMessage } from '../stream/chat';

function message(
  role: ChatMessage['role'],
  content: string,
  extra: Partial<ChatMessage> = {},
): ChatMessage {
  return { id: 'm1', role, content, ...extra };
}

describe('createMessageList', () => {
  it('is an aria-live log region', () => {
    const list = createMessageList();
    expect(list.getAttribute('role')).toBe('log');
    expect(list.getAttribute('aria-live')).toBe('polite');
    expect(list.getAttribute('aria-relevant')).toBe('additions');
  });
});

describe('createBubble', () => {
  it('renders user content as plain text', () => {
    const bubble = createBubble(message('user', 'hi <script>alert(1)</script>'));
    expect(bubble.className).toContain('wc-role-user');
    expect(bubble.textContent).toBe('hi <script>alert(1)</script>');
    expect(bubble.querySelector('script')).toBeNull();
  });

  it('renders assistant content through the sanitized markdown renderer', () => {
    const bubble = createBubble(message('assistant', '**bold** and [x](javascript:alert(1))'));
    expect(bubble.className).toContain('wc-role-assistant');
    expect(bubble.querySelector('.wc-bubble-content')?.innerHTML).toContain(
      '<strong>bold</strong>',
    );
    expect(bubble.innerHTML).not.toContain('javascript:');
    expect(bubble.querySelector('a')).toBeNull();
  });

  it('marks error and streaming bubbles', () => {
    const failed = createBubble(message('assistant', 'oops', { error: true }));
    expect(failed.className).toContain('wc-bubble-error');

    const streaming = createBubble(message('assistant', 'part', { streaming: true }));
    expect(streaming.className).toContain('wc-streaming');
  });
});

describe('createWelcomeBubble', () => {
  it('renders the welcome text as an assistant bubble', () => {
    const bubble = createWelcomeBubble('**Hi!** How can I help?');
    expect(bubble.className).toContain('wc-welcome');
    expect(bubble.className).toContain('wc-role-assistant');
    expect(bubble.querySelector('.wc-bubble-content')?.innerHTML).toContain('<strong>Hi!</strong>');
  });
});

describe('setBusy', () => {
  it('toggles aria-busy on the message list', () => {
    const list = createMessageList();
    setBusy(list, true);
    expect(list.getAttribute('aria-busy')).toBe('true');
    setBusy(list, false);
    expect(list.hasAttribute('aria-busy')).toBe(false);
  });
});

describe('renderMessages / appendMessage', () => {
  it('renders every message in order', () => {
    const list = createMessageList();
    renderMessages(list, [message('user', 'one'), message('assistant', '**two**')]);
    expect(list.querySelectorAll('.wc-bubble').length).toBe(2);
    expect(list.querySelector('.wc-role-user')?.textContent).toBe('one');
  });

  it('appends a single message bubble', () => {
    const list = createMessageList();
    appendMessage(list, message('user', 'one'));
    appendMessage(list, message('assistant', 'two'));
    expect(list.querySelectorAll('.wc-bubble').length).toBe(2);
  });
});
