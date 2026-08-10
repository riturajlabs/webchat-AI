/**
 * Message bubbles (plan §5, WCAG 2.2 AA).
 *
 * User/assistant styled bubbles inside an `aria-live="polite"` region so
 * streaming updates are announced. Assistant content is rendered via the
 * restricted markdown sanitizer; user content is rendered as plain text.
 */

import { renderMarkdown } from '../markdown/render';
import type { ChatMessage } from '../stream/chat';

export function createBubble(message: ChatMessage): HTMLElement {
  const bubble = document.createElement('div');
  bubble.className = `wc-bubble wc-role-${message.role}`;
  bubble.dataset.messageId = message.id;

  if (message.role === 'user') {
    bubble.textContent = message.content;
  } else {
    const content = document.createElement('div');
    content.className = 'wc-bubble-content';
    content.innerHTML = renderMarkdown(message.content);
    bubble.appendChild(content);
  }

  if (message.error) {
    bubble.classList.add('wc-bubble-error');
  }
  if (message.streaming) {
    bubble.classList.add('wc-streaming');
  }
  return bubble;
}

export function createMessageList(): HTMLElement {
  const list = document.createElement('div');
  list.className = 'wc-messages';
  list.setAttribute('role', 'log');
  list.setAttribute('aria-live', 'polite');
  list.setAttribute('aria-relevant', 'additions');
  return list;
}

/** Assistant-styled welcome bubble shown before the first exchange (plan §5). */
export function createWelcomeBubble(message: string): HTMLElement {
  const bubble = document.createElement('div');
  bubble.className = 'wc-bubble wc-role-assistant wc-welcome';
  const content = document.createElement('div');
  content.className = 'wc-bubble-content';
  content.innerHTML = renderMarkdown(message);
  bubble.appendChild(content);
  return bubble;
}

/** Toggle `aria-busy` on the message list while a reply streams (4.1.3). */
export function setBusy(list: HTMLElement, busy: boolean): void {
  if (busy) {
    list.setAttribute('aria-busy', 'true');
  } else {
    list.removeAttribute('aria-busy');
  }
}

/** Render the full message list into `list`, preserving the last element in view. */
export function renderMessages(list: HTMLElement, messages: ChatMessage[]): void {
  const stickToBottom = isNearBottom(list);
  list.replaceChildren();
  for (const message of messages) {
    list.appendChild(createBubble(message));
  }
  if (stickToBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

/** Append a single message bubble, keeping the view pinned to the bottom. */
export function appendMessage(list: HTMLElement, message: ChatMessage): void {
  const stickToBottom = isNearBottom(list);
  list.appendChild(createBubble(message));
  if (stickToBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

function isNearBottom(list: HTMLElement): boolean {
  return list.scrollHeight - list.scrollTop - list.clientHeight < 40;
}
