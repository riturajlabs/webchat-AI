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
import type { WidgetPublicConfig } from '../config/types';
import {
  createFeedbackControl,
  type FeedbackControl,
  type FeedbackSubmitPayload,
} from './feedback';
import { botGlyph, externalLinkGlyph } from './icons';

/** Assistant messages longer than this are collapsed behind "Show more". */
export const LONG_MESSAGE_CHARS = 1200;

/** Last-rendered content per bubble, so unchanged messages skip DOM work. */
const renderedContent = new WeakMap<HTMLElement, string>();
/** Last-rendered timestamp label per bubble. */
const renderedTime = new WeakMap<HTMLElement, string>();
/** Signature of the sources currently rendered into a bubble. */
const renderedSources = new WeakMap<HTMLElement, string>();
/** Feedback control rendered under a bubble (keyed per bubble). */
const renderedFeedback = new WeakMap<HTMLElement, FeedbackControl>();
/** Message ids the user has expanded (sticky across re-renders). */
const expanded = new Set<string>();

/** Format a millisecond timestamp as the local `HH:MM` clock label. */
export function formatTime(timestamp?: number): string {
  if (!timestamp) {
    return '';
  }
  const date = new Date(timestamp);
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

/**
 * Host-provided feedback submit handlers, injected by `wireMessageActions`,
 * keyed by message list so multiple widgets on one page never route each
 * other's submissions (production hardening).
 */
type FeedbackSubmitHandler = (messageId: string, payload: FeedbackSubmitPayload) => void;

const feedbackHandlers = new WeakMap<HTMLElement, FeedbackSubmitHandler>();

function isSafeSourceUrl(href: string): boolean {
  return /^(https?:\/\/|#|\/|mailto:)/i.test(href);
}

/** Heading shown above the citation cards (friendly, not "Sources"). */
const SOURCES_LABEL = 'Learn more';
/** Cards visible before the "View all sources" toggle kicks in. */
const VISIBLE_SOURCES = 3;
/** Unique `aria-controls` ids for the expandable source lists. */
let sourceListIdCounter = 0;

/** Hostname of an http(s) URL, or null when the URL is unparsable/unsafe. */
function hostOf(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.hostname;
    }
  } catch {
    /* unparsable URL */
  }
  return null;
}

/** Compact display URL: no protocol, no www, trailing slash stripped. */
function displayUrl(url: string): string {
  try {
    const parsed = new URL(url);
    let out = parsed.hostname.replace(/^www\./, '');
    const path = parsed.pathname.replace(/\/+$/, '');
    if (path) {
      out += path;
    }
    return out;
  } catch {
    return url;
  }
}

/**
 * One "Learn more" card: title + domain/path + "Open" external link.
 * The whole card is the link when the URL is safe; unsafe schemes render a
 * non-interactive card (title only) so nothing dangerous ever becomes clickable.
 */
function createSourceCard(source: ChatSource, index: number): HTMLElement {
  const item = document.createElement('li');
  item.className = 'wc-source-item';
  if (index >= VISIBLE_SOURCES) {
    item.classList.add('wc-source-hidden');
  }

  const url = source.url ?? '';
  const safeUrl = Boolean(url) && isSafeSourceUrl(url);
  const host = safeUrl ? hostOf(url) : null;
  const title = source.title || host || url || 'Source';

  const body = document.createElement('span');
  body.className = 'wc-source-body';

  const titleEl = document.createElement('span');
  titleEl.className = 'wc-source-title';
  titleEl.textContent = title;
  body.appendChild(titleEl);

  if (safeUrl) {
    const meta = document.createElement('span');
    meta.className = 'wc-source-meta';

    const urlEl = document.createElement('span');
    urlEl.className = 'wc-source-url';
    urlEl.textContent = displayUrl(url);

    const read = document.createElement('span');
    read.className = 'wc-source-read';
    read.textContent = 'Open';
    read.appendChild(externalLinkGlyph());

    meta.appendChild(urlEl);
    meta.appendChild(read);
    body.appendChild(meta);
  }

  if (safeUrl) {
    const link = document.createElement('a');
    link.className = 'wc-source-link';
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.appendChild(body);
    item.appendChild(link);
  } else {
    const card = document.createElement('div');
    card.className = 'wc-source-link wc-source-link-plain';
    card.appendChild(body);
    item.appendChild(card);
  }
  return item;
}

/** "View all sources (N)" / "Show fewer" toggle for lists longer than 3. */
function createSourcesToggle(block: HTMLElement, list: HTMLElement, total: number): void {
  const hidden = total - VISIBLE_SOURCES;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'wc-sources-toggle';
  button.textContent = `View all sources (${hidden})`;
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-controls', list.id);
  button.addEventListener('click', () => {
    const open = block.classList.toggle('wc-sources-expanded');
    button.textContent = open ? 'Show fewer' : `View all sources (${hidden})`;
    button.setAttribute('aria-expanded', String(open));
  });
  block.appendChild(button);
}

/** Deduplicate sources by URL (keeps first occurrence). */
function deduplicateSources(sources: ChatSource[]): ChatSource[] {
  const seen = new Set<string>();
  const result: ChatSource[] = [];
  for (const source of sources) {
    const url = source.url?.trim().toLowerCase();
    if (!url || !seen.has(url)) {
      if (url) {
        seen.add(url);
      }
      result.push(source);
    }
  }
  return result;
}

/** Render the "Learn more" citation cards (untrusted input -> text). */
export function renderSources(sources: ChatSource[]): HTMLElement {
  const block = document.createElement('div');
  block.className = 'wc-sources';

  const label = document.createElement('span');
  label.className = 'wc-sources-label';
  label.textContent = SOURCES_LABEL;
  block.appendChild(label);

  const list = document.createElement('ol');
  list.className = 'wc-sources-list';
  list.id = `wc-sources-list-${++sourceListIdCounter}`;
  sources.forEach((source, index) => list.appendChild(createSourceCard(source, index)));
  block.appendChild(list);

  if (sources.length > VISIBLE_SOURCES) {
    createSourcesToggle(block, list, sources.length);
  }
  return block;
}

export function createBubble(message: ChatMessage, list?: HTMLElement): HTMLElement {
  const bubble = document.createElement('div');
  bubble.className = `wc-bubble wc-role-${message.role}`;
  bubble.dataset.messageId = message.id;

  if (message.role === 'user') {
    const text = document.createElement('span');
    text.className = 'wc-bubble-text';
    bubble.appendChild(text);
  } else {
    const content = document.createElement('div');
    content.className = 'wc-bubble-content';
    bubble.appendChild(content);
  }

  syncBubble(bubble, message, list);
  renderedContent.set(bubble, message.content);
  return bubble;
}

/** Update an existing bubble to match `message` (skips work when unchanged). */
function syncBubble(bubble: HTMLElement, message: ChatMessage, list?: HTMLElement): void {
  const isAssistant = message.role === 'assistant';
  bubble.classList.toggle('wc-role-user', message.role === 'user');
  bubble.classList.toggle('wc-role-assistant', isAssistant);
  bubble.classList.toggle('wc-bubble-error', Boolean(message.error));
  bubble.classList.toggle('wc-streaming', Boolean(message.streaming));
  bubble.classList.toggle('wc-stopped', Boolean(message.stopped));

  syncTime(bubble, message);

  if (message.role === 'user') {
    const text = bubble.querySelector<HTMLElement>('.wc-bubble-text');
    if (text && renderedContent.get(bubble) !== message.content) {
      text.textContent = message.content;
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

  // Typing indicator while streaming/thinking with no content yet.
  syncTypingIndicator(bubble, message);

  // Long-message collapse (only when not streaming — content is still growing).
  syncCollapse(bubble, message);

  // Sources + per-message retry (rebuilt only when their inputs change).
  syncSources(bubble, message);
  syncRetry(bubble, message);

  // Visitor feedback (Phase 12.4): only for completed assistant answers.
  syncFeedback(bubble, message, list);
}

/** Small muted timestamp under completed messages (optional polish). */
function syncTime(bubble: HTMLElement, message: ChatMessage): void {
  let time = bubble.querySelector<HTMLElement>('.wc-time');
  const visible = Boolean(message.content) && !message.streaming;
  if (!visible) {
    if (time) {
      time.remove();
    }
    renderedTime.delete(bubble);
    return;
  }
  const label = formatTime(message.createdAt);
  if (!time) {
    time = document.createElement('span');
    time.className = 'wc-time';
    time.setAttribute('aria-hidden', 'true');
    bubble.appendChild(time);
  }
  if (renderedTime.get(bubble) !== label) {
    time.textContent = label;
    renderedTime.set(bubble, label);
  }
}

function syncTypingIndicator(bubble: HTMLElement, message: ChatMessage): void {
  let typing = bubble.querySelector<HTMLElement>('.wc-typing');
  const showTyping = (message.streaming || message.thinking) && message.content.length === 0;
  if (showTyping) {
    if (!typing) {
      typing = document.createElement('span');
      typing.className = 'wc-typing';
      typing.setAttribute('aria-hidden', 'true');

      const dots = document.createElement('span');
      dots.className = 'wc-typing-dots';
      for (let i = 0; i < 3; i += 1) {
        dots.appendChild(document.createElement('i'));
      }

      typing.appendChild(dots);
      bubble.appendChild(typing);
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

function syncSources(bubble: HTMLElement, message: ChatMessage): void {
  const signature =
    (message.streaming ? 's' : 'd') +
    (message.sources ?? [])
      .map((s) => `${s.citation ?? ''}|${s.url ?? ''}|${s.title ?? ''}`)
      .join('\n');
  if (renderedSources.get(bubble) === signature) {
    return;
  }
  bubble.querySelector('.wc-sources')?.remove();
  // Sources are only rendered after the streaming turn completes (not during).
  // Duplicates are deduped by URL before rendering.
  if (message.sources && message.sources.length > 0 && !message.streaming) {
    const deduped = deduplicateSources(message.sources);
    if (deduped.length > 0) {
      bubble.appendChild(renderSources(deduped));
    }
  }
  renderedSources.set(bubble, signature);
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

/**
 * Render/update the visitor feedback control under a completed assistant
 * answer. The control is created once per bubble and re-synced on feedback
 * status transitions; the visitor's in-form input is never lost.
 */
function syncFeedback(bubble: HTMLElement, message: ChatMessage, list?: HTMLElement): void {
  const rateable =
    message.role === 'assistant' &&
    !message.streaming &&
    !message.error &&
    Boolean(message.messageId);

  const control = renderedFeedback.get(bubble);
  if (!rateable) {
    if (control) {
      control.element.remove();
      renderedFeedback.delete(bubble);
    }
    return;
  }

  if (!control) {
    // Resolve the submit handler at click time from the owning list so a
    // second widget mounting later can't hijack this bubble's submissions.
    const next = createFeedbackControl({
      onSubmit: (payload) => {
        const handler = list ? feedbackHandlers.get(list) : undefined;
        handler?.(message.id, payload);
      },
    });
    renderedFeedback.set(bubble, next);
    bubble.appendChild(next.element);
    next.sync(message.feedback?.status ?? 'idle');
    return;
  }

  const status = message.feedback?.status ?? 'idle';
  const lastStatus = control.element.dataset.status;
  if (lastStatus !== status) {
    control.element.dataset.status = status;
    control.sync(status);
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

/**
 * Rich empty state shown before the first exchange: a brand avatar next to the
 * config-driven welcome message. The suggestion chips render separately.
 */
export function createEmptyState(config: WidgetPublicConfig): HTMLElement {
  const root = document.createElement('div');
  root.className = 'wc-empty-state';

  const avatar = document.createElement('div');
  avatar.className = 'wc-empty-avatar';
  avatar.setAttribute('aria-hidden', 'true');
  const avatarUrl = config.avatar_url || config.logo_url;
  if (avatarUrl) {
    const img = document.createElement('img');
    img.className = 'wc-empty-avatar-img';
    img.src = avatarUrl;
    img.alt = '';
    img.referrerPolicy = 'no-referrer';
    avatar.appendChild(img);
  } else {
    avatar.appendChild(botGlyph());
  }
  root.appendChild(avatar);

  const bubble = createWelcomeBubble(config.welcome_message);
  root.appendChild(bubble);

  return root;
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

  // During streaming this runs per animation frame; only move nodes whose
  // position actually changed (append-only conversations never do) instead of
  // re-inserting every bubble on each pass.
  let prevElement: Element | null = null;
  for (const message of messages) {
    const bubble = existing.get(message.id);
    if (bubble) {
      syncBubble(bubble, message, list);
      if (bubble.previousElementSibling !== prevElement) {
        list.appendChild(bubble); // keeps order if the list shrank/edited
      }
      prevElement = bubble;
    } else {
      const created = createBubble(message, list);
      list.appendChild(created);
      prevElement = created;
    }
  }

  for (const [id, bubble] of existing) {
    if (!messages.some((m) => m.id === id)) {
      bubble.remove();
    }
  }

  // The empty state / welcome bubble are placeholders shown only before the
  // first exchange.
  if (messages.length > 0) {
    list.querySelector('.wc-welcome')?.remove();
    list.querySelector('.wc-empty-state')?.remove();
  }

  if (stickToBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

/** Append a single message bubble, keeping the view pinned to the bottom. */
export function appendMessage(list: HTMLElement, message: ChatMessage): void {
  const stickToBottom = isNearBottom(list);
  list.appendChild(createBubble(message, list));
  if (stickToBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

/** Re-sync a single message's bubble (used by the "Show more" toggle). */
export function updateMessage(list: HTMLElement, message: ChatMessage): void {
  const bubble = list.querySelector<HTMLElement>(`[data-message-id="${message.id}"]`);
  if (bubble) {
    syncBubble(bubble, message, list);
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
    onFeedbackSubmit?: (messageId: string, payload: FeedbackSubmitPayload) => void;
  },
): () => void {
  feedbackHandlers.set(list, handlers.onFeedbackSubmit ?? (() => {}));
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
