/**
 * Message bubbles (plan §5, WCAG 2.2 AA).
 *
 * User/assistant styled bubbles inside an `aria-live="polite"` region so
 * streaming updates are announced. Assistant content is rendered via the
 * restricted markdown sanitizer; user content is rendered as plain text.
 *
 * Phase 10 changes:
 * - **Incremental reconciliation.** `renderMessages` no longer rebuilds the
 *   list on every token. It diffs against the existing bubbles (keyed by
 *   `data-message-id`) and touches only the message whose content actually
 *   changed — the active streaming bubble. Auto-scroll is preserved.
 * - Animated typing indicator while the assistant turn has no content yet.
 * - Per-message Retry action on failed assistant bubbles (event delegation,
 *   see `mount.ts`).
 * - Citation/source list rendering when the SSE `sources` event provides data.
 * - "Show more/less" collapse for very long assistant messages.
 */

import { renderMarkdown } from '../markdown/render';
import type { ChatMessage, ChatSource } from '../stream/chat';

/** Assistant messages longer than this are collapsed behind "Show more". */
export const LONG_MESSAGE_CHARS = 1200;

/** Last-rendered content per bubble, so unchanged messages skip DOM work. */
const renderedContent = new WeakMap<HTMLElement, string>();
/** Signature of the sources currently rendered into a bubble. */
const renderedSources = new WeakMap<HTMLElement, string>();
/** Message ids the user has expanded (sticky across re-renders). */
const expanded = new Set<string>();

function isSafeSourceUrl(href: string): boolean {
  return /^(https?:\/\/|#|\/|mailto:)/i.test(href);
}

/** Render the citation/source list using DOM APIs (untrusted input → text). */
export function renderSources(sources: ChatSource[]): HTMLElement {
  const block = document.createElement('div');
  block.className = 'wc-sources';

  const label = document.createElement('span');
  label.className = 'wc-sources-label';
  label.textContent = 'Sources';
  block.appendChild(label);

  const list = document.createElement('ol');
  list.className = 'wc-sources-list';
  for (const source of sources) {
    const item = document.createElement('li');
    const citation = source.citation ? `${source.citation}. ` : '';
    const title = source.title || source.url || 'Source';
    if (source.url && isSafeSourceUrl(source.url)) {
      const link = document.createElement('a');
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = `${citation}${title}`;
      item.appendChild(link);
    } else {
      item.textContent = `${citation}${title}`;
    }
    list.appendChild(item);
  }
  block.appendChild(list);
  return block;
}

export function createBubble(message: ChatMessage): HTMLElement {
  const bubble = document.createElement('div');
  bubble.className = `wc-bubble wc-role-${message.role}`;
  bubble.dataset.messageId = message.id;

  if (message.role === 'user') {
    bubble.textContent = message.content;
  } else {
    const content = document.createElement('div');
    content.className = 'wc-bubble-content';
    bubble.appendChild(content);
  }

  syncBubble(bubble, message);
  renderedContent.set(bubble, message.content);
  return bubble;
}

/** Update an existing bubble to match `message` (skips work when unchanged). */
function syncBubble(bubble: HTMLElement, message: ChatMessage): void {
  const isAssistant = message.role === 'assistant';
  bubble.classList.toggle('wc-role-user', message.role === 'user');
  bubble.classList.toggle('wc-role-assistant', isAssistant);
  bubble.classList.toggle('wc-bubble-error', Boolean(message.error));
  bubble.classList.toggle('wc-streaming', Boolean(message.streaming));
  bubble.classList.toggle('wc-stopped', Boolean(message.stopped));

  if (message.role === 'user') {
    if (renderedContent.get(bubble) !== message.content) {
      bubble.textContent = message.content;
    }
    return;
  }

  // Assistant content: re-render markdown only when the text actually changed.
  if (renderedContent.get(bubble) !== message.content) {
    let content = bubble.querySelector<HTMLElement>('.wc-bubble-content');
    if (!content) {
      content = document.createElement('div');
      content.className = 'wc-bubble-content';
      bubble.prepend(content);
    }
    content.innerHTML = renderMarkdown(message.content);
  }

  // Typing indicator while streaming with no content yet.
  syncTypingIndicator(bubble, message);

  // Long-message collapse (only when not streaming — content is still growing).
  syncCollapse(bubble, message);

  // Sources + per-message retry (rebuilt only when their inputs change).
  syncSources(bubble, message);
  syncRetry(bubble, message);
}

function syncTypingIndicator(bubble: HTMLElement, message: ChatMessage): void {
  let typing = bubble.querySelector<HTMLElement>('.wc-typing');
  if (message.streaming && message.content.length === 0) {
    if (!typing) {
      typing = document.createElement('span');
      typing.className = 'wc-typing';
      typing.setAttribute('aria-hidden', 'true');
      for (let i = 0; i < 3; i += 1) {
        typing.appendChild(document.createElement('i'));
      }
      bubble.insertBefore(typing, bubble.querySelector('.wc-bubble-content'));
    }
  } else if (typing) {
    typing.remove();
  }
}

function syncCollapse(bubble: HTMLElement, message: ChatMessage): void {
  const isLong = message.content.length > LONG_MESSAGE_CHARS && !message.streaming;
  bubble.classList.toggle('wc-long', isLong);
  if (isLong) {
    bubble.classList.toggle('wc-collapsed', !expanded.has(message.id));
  } else {
    bubble.classList.remove('wc-collapsed');
  }

  let toggle = bubble.querySelector<HTMLButtonElement>('.wc-more-toggle');
  if (isLong) {
    if (!toggle) {
      toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'wc-more-toggle';
      bubble.appendChild(toggle);
    }
    const open = expanded.has(message.id);
    toggle.textContent = open ? 'Show less' : 'Show more';
    toggle.setAttribute('aria-expanded', String(open));
  } else if (toggle) {
    toggle.remove();
  }
}

function sourcesSignature(sources: ChatSource[] | undefined): string {
  return (sources ?? [])
    .map((s) => `${s.citation ?? ''}|${s.url ?? ''}|${s.title ?? ''}`)
    .join('\n');
}

function syncSources(bubble: HTMLElement, message: ChatMessage): void {
  const signature = sourcesSignature(message.sources);
  if (renderedSources.get(bubble) === signature) {
    return;
  }
  renderedSources.set(bubble, signature);
  bubble.querySelector('.wc-sources')?.remove();
  if (message.sources && message.sources.length > 0) {
    bubble.appendChild(renderSources(message.sources));
  }
}

function syncRetry(bubble: HTMLElement, message: ChatMessage): void {
  let retry = bubble.querySelector<HTMLButtonElement>('.wc-retry-message');
  const showRetry = message.role === 'assistant' && message.error;
  if (showRetry) {
    if (!retry) {
      retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'wc-retry-message';
      retry.textContent = 'Retry';
      retry.setAttribute('aria-label', 'Retry sending this message');
      bubble.appendChild(retry);
    }
  } else if (retry) {
    retry.remove();
  }
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

/**
 * Render `messages` into `list` incrementally: bubbles are created once and
 * only the changed message is re-rendered (streaming optimization, Phase 10).
 * Auto-scroll is preserved when the view is already near the bottom.
 */
export function renderMessages(list: HTMLElement, messages: ChatMessage[]): void {
  const stickToBottom = isNearBottom(list);
  const existing = new Map<string, HTMLElement>();
  for (const bubble of list.querySelectorAll<HTMLElement>('[data-message-id]')) {
    existing.set(bubble.dataset.messageId ?? '', bubble);
  }

  for (const message of messages) {
    const bubble = existing.get(message.id);
    if (bubble) {
      syncBubble(bubble, message);
      list.appendChild(bubble); // keeps order if the list shrank/edited
    } else {
      list.appendChild(createBubble(message));
    }
  }

  for (const [id, bubble] of existing) {
    if (!messages.some((m) => m.id === id)) {
      bubble.remove();
    }
  }

  // The welcome bubble is a placeholder shown only before the first exchange.
  if (messages.length > 0) {
    list.querySelector('.wc-welcome')?.remove();
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

/** Re-sync a single message's bubble (used by the "Show more" toggle). */
export function updateMessage(list: HTMLElement, message: ChatMessage): void {
  const bubble = list.querySelector<HTMLElement>(`[data-message-id="${message.id}"]`);
  if (bubble) {
    syncBubble(bubble, message);
  }
}

/** Toggle the "Show more/less" collapse for a message and re-sync its bubble. */
export function toggleExpanded(list: HTMLElement, message: ChatMessage): void {
  if (expanded.has(message.id)) {
    expanded.delete(message.id);
  } else {
    expanded.add(message.id);
  }
  updateMessage(list, message);
}

/**
 * Delegate the interactive bubble actions with one listener per list:
 * copy-code buttons, per-message Retry, and the show-more toggle. The DOM stays
 * inert; the host (mount) injects the real behaviors via `handlers`.
 */
export function wireMessageActions(
  list: HTMLElement,
  handlers: {
    onCopyCode: (code: string) => void;
    onRetry: (messageId: string) => void;
    onToggleMore: (messageId: string) => void;
  },
): () => void {
  const onBubbleClick = (event: MouseEvent): void => {
    const target = event.target as HTMLElement | null;
    if (!target) {
      return;
    }

    const copy = target.closest<HTMLButtonElement>('.wc-code-copy');
    if (copy) {
      const code = copy.closest('.wc-code')?.querySelector<HTMLElement>('code')?.textContent;
      if (code !== undefined) {
        handlers.onCopyCode(code);
      }
      return;
    }

    const retry = target.closest<HTMLButtonElement>('.wc-retry-message');
    if (retry) {
      const bubble = retry.closest<HTMLElement>('[data-message-id]');
      if (bubble?.dataset.messageId) {
        handlers.onRetry(bubble.dataset.messageId);
      }
      return;
    }

    const toggle = target.closest<HTMLButtonElement>('.wc-more-toggle');
    if (toggle) {
      const bubble = toggle.closest<HTMLElement>('[data-message-id]');
      if (bubble?.dataset.messageId) {
        handlers.onToggleMore(bubble.dataset.messageId);
      }
    }
  };

  list.addEventListener('click', onBubbleClick);
  return () => list.removeEventListener('click', onBubbleClick);
}

function isNearBottom(list: HTMLElement): boolean {
  return list.scrollHeight - list.scrollTop - list.clientHeight < 40;
}
