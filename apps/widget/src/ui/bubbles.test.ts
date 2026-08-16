import { describe, expect, it, vi } from 'vitest';
import {
  appendMessage,
  createBubble,
  createMessageList,
  createWelcomeBubble,
  renderMessages,
  setBusy,
  toggleExpanded,
  wireMessageActions,
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

  it('shows a typing indicator while streaming with no content yet', () => {
    const typing = createBubble(message('assistant', '', { streaming: true }));
    expect(typing.querySelector('.wc-typing')).toBeTruthy();

    const started = createBubble(message('assistant', 'part', { streaming: true }));
    expect(started.querySelector('.wc-typing')).toBeNull();
  });

  it('adds a per-message Retry action to failed assistant bubbles', () => {
    const failed = createBubble(message('assistant', 'oops', { error: true }));
    const retry = failed.querySelector<HTMLButtonElement>('.wc-retry-message');
    expect(retry).toBeTruthy();
    expect(retry?.getAttribute('aria-label')).toBeTruthy();

    expect(createBubble(message('assistant', 'ok')).querySelector('.wc-retry-message')).toBeNull();
  });

  it('renders the source/citation list', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: [
          { url: 'https://docs.example.com/x', title: 'Docs X' },
          { url: 'javascript:alert(1)', title: 'Evil' },
        ],
      }),
    );
    const sources = bubble.querySelector('.wc-sources');
    expect(sources).toBeTruthy();
    const link = sources?.querySelector<HTMLAnchorElement>('a');
    expect(link?.textContent).toContain('Docs X');
    expect(link?.href).toContain('https://docs.example.com/x');
    expect(bubble.innerHTML).not.toContain('javascript:');
  });

  it('renders no source block when the SSE sources event is empty', () => {
    const bubble = createBubble(message('assistant', 'answer', { sources: [] }));
    expect(bubble.querySelector('.wc-sources')).toBeNull();
  });

  it('renders no source block when sources is undefined (RAG did not return any)', () => {
    const bubble = createBubble(message('assistant', 'answer'));
    expect(bubble.querySelector('.wc-sources')).toBeNull();
  });

  it('rejects unsafe URL schemes and falls back to plain text', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: [
          { url: 'javascript:alert(1)', title: 'XSS attempt' },
          { url: 'data:text/html,<script>alert(1)</script>', title: 'Data URL' },
          { url: 'vbscript:msgbox(1)', title: 'VBScript' },
        ],
      }),
    );
    const sources = bubble.querySelector('.wc-sources');
    expect(sources).toBeTruthy();
    // No <a> tags should be rendered for unsafe schemes.
    expect(sources?.querySelectorAll('a').length).toBe(0);
    // Plain-text fallback keeps the title visible (label-only — title text only).
    expect(sources?.textContent).toContain('XSS attempt');
    expect(sources?.textContent).toContain('Data URL');
    expect(sources?.textContent).toContain('VBScript');
    // No dangerous scheme leaks into the rendered HTML.
    expect(bubble.innerHTML).not.toMatch(/javascript:/i);
    expect(bubble.innerHTML).not.toMatch(/data:/i);
    expect(bubble.innerHTML).not.toMatch(/vbscript:/i);
  });

  it('renders multiple sources as Learn-more cards in order, opening safely in a new tab', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: [
          { url: 'https://example.com/home', title: 'Homepage', citation: '1' },
          { url: 'https://example.com/pricing', title: 'Pricing', citation: '2' },
          { url: 'https://example.com/about', title: 'About' },
        ],
      }),
    );
    const items = bubble.querySelectorAll('.wc-sources-list li');
    expect(items.length).toBe(3);
    const links = bubble.querySelectorAll<HTMLAnchorElement>('.wc-sources-list a');
    expect(links.length).toBe(3);
    expect(links[0]?.querySelector('.wc-source-title')?.textContent).toBe('Homepage');
    expect(links[0]?.querySelector('.wc-source-citation')?.textContent).toBe('1');
    expect(links[0]?.getAttribute('target')).toBe('_blank');
    expect(links[0]?.getAttribute('rel')).toBe('noopener noreferrer');
    expect(links[1]?.querySelector('.wc-source-title')?.textContent).toBe('Pricing');
    // No citation field -> falls back to the list position.
    expect(links[2]?.querySelector('.wc-source-citation')?.textContent).toBe('3');
  });

  it('renders a favicon, derived description, truncated URL and Read-more per card', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: [{ url: 'https://www.example.com/courses/admission', title: 'Admission' }],
      }),
    );
    const card = bubble.querySelector<HTMLAnchorElement>('.wc-sources-list a');
    const favicon = card?.querySelector<HTMLImageElement>('.wc-source-favicon img');
    expect(favicon?.src).toContain('icons.duckduckgo.com');
    expect(favicon?.src).toContain('example.com');
    expect(card?.querySelector('.wc-source-desc')?.textContent).toBe('courses admission');
    // URL is protocol-stripped, www-stripped, and present as truncated text.
    expect(card?.querySelector('.wc-source-url')?.textContent).toBe(
      'example.com/courses/admission',
    );
    expect(card?.querySelector('.wc-source-read')?.textContent).toContain('Read more');
  });

  it('exposes a friendly "Learn more" label above the citation cards (a11y landmark)', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: [{ url: 'https://example.com', title: 'Example' }],
      }),
    );
    const label = bubble.querySelector<HTMLElement>('.wc-sources-label');
    expect(label?.textContent).toBe('Learn more');
    expect(label?.tagName).toBe('SPAN');
  });

  it('shows only the first 3 sources and expands the rest via the toggle', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: Array.from({ length: 5 }, (_, index) => ({
          url: `https://example.com/page/${index}`,
          title: `Source ${index + 1}`,
        })),
      }),
    );
    const sources = bubble.querySelector('.wc-sources');
    expect(sources?.querySelectorAll('.wc-source-item').length).toBe(5);
    expect(sources?.querySelectorAll('.wc-source-item.wc-source-hidden').length).toBe(2);

    const toggle = sources?.querySelector<HTMLButtonElement>('.wc-sources-toggle');
    expect(toggle?.textContent).toBe('View all sources (2)');
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    expect(toggle?.getAttribute('aria-controls')).toBeTruthy();
    expect(sources?.classList.contains('wc-sources-expanded')).toBe(false);

    toggle?.click();
    expect(sources?.classList.contains('wc-sources-expanded')).toBe(true);
    expect(toggle?.textContent).toBe('Show fewer');
    expect(toggle?.getAttribute('aria-expanded')).toBe('true');

    toggle?.click();
    expect(sources?.classList.contains('wc-sources-expanded')).toBe(false);
    expect(toggle?.textContent).toBe('View all sources (2)');
  });

  it('shows no expand toggle when there are 3 or fewer sources', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: [
          { url: 'https://example.com/a', title: 'A' },
          { url: 'https://example.com/b', title: 'B' },
          { url: 'https://example.com/c', title: 'C' },
        ],
      }),
    );
    expect(bubble.querySelector('.wc-sources-toggle')).toBeNull();
  });

  it('renders unsafe-source cards without any anchor or external assets', () => {
    const bubble = createBubble(
      message('assistant', 'answer', {
        sources: [{ url: 'javascript:alert(1)', title: 'XSS attempt' }],
      }),
    );
    const card = bubble.querySelector<HTMLElement>('.wc-sources-list .wc-source-link');
    expect(card?.classList.contains('wc-source-link-plain')).toBe(true);
    expect(card?.querySelector('.wc-source-title')?.textContent).toBe('XSS attempt');
    // No clickable link, no favicon request, no "Read more" affordance.
    expect(bubble.querySelector('.wc-sources-list a')).toBeNull();
    expect(bubble.querySelector('.wc-sources-list img')).toBeNull();
    expect(bubble.querySelector('.wc-source-read')).toBeNull();
    expect(bubble.innerHTML).not.toMatch(/javascript:/i);
  });

  it('collapses very long answers behind a Show-more toggle', () => {
    const long = message('assistant', 'x'.repeat(1500));
    const bubble = createBubble(long);
    expect(bubble.className).toContain('wc-long');
    expect(bubble.className).toContain('wc-collapsed');
    const toggle = bubble.querySelector<HTMLButtonElement>('.wc-more-toggle');
    expect(toggle?.textContent).toBe('Show more');
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');

    const list = createMessageList();
    list.appendChild(bubble);
    toggleExpanded(list, long);
    expect(bubble.classList.contains('wc-collapsed')).toBe(false);
    expect(toggle?.textContent).toBe('Show less');
    expect(toggle?.getAttribute('aria-expanded')).toBe('true');
  });

  it('does not collapse while the turn is still streaming', () => {
    const streaming = createBubble(message('assistant', 'x'.repeat(1500), { streaming: true }));
    expect(streaming.classList.contains('wc-long')).toBe(false);
    expect(streaming.querySelector('.wc-more-toggle')).toBeNull();
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

  it('reconciles incrementally without rebuilding unchanged bubbles', () => {
    const list = createMessageList();
    renderMessages(list, [
      message('user', 'one', { id: 'u1' }),
      message('assistant', '', { id: 'a1' }),
    ]);
    const userBubble = list.querySelector('[data-message-id="u1"]');
    const asstBubble = list.querySelector('[data-message-id="a1"]');

    // Stream a delta into the assistant bubble.
    renderMessages(list, [
      message('user', 'one', { id: 'u1' }),
      message('assistant', 'He', { id: 'a1', streaming: true }),
    ]);
    expect(list.querySelector('[data-message-id="u1"]')).toBe(userBubble);
    expect(list.querySelector('[data-message-id="a1"]')).toBe(asstBubble);
    expect(asstBubble?.querySelector('.wc-bubble-content')?.textContent).toBe('He');
  });

  it('removes the welcome bubble once a real exchange begins', () => {
    const list = createMessageList();
    list.appendChild(createWelcomeBubble('Hi!'));
    renderMessages(list, [message('user', 'hello', { id: 'u1' })]);
    expect(list.querySelector('.wc-welcome')).toBeNull();
    expect(list.querySelectorAll('.wc-bubble').length).toBe(1);
  });
});

describe('wireMessageActions', () => {
  it('delegates copy / retry / show-more clicks', () => {
    const list = createMessageList();
    const onCopyCode = vi.fn();
    const onRetry = vi.fn();
    const onToggleMore = vi.fn();
    wireMessageActions(list, { onCopyCode, onRetry, onToggleMore });

    const code = message('assistant', '```js\nconst x = 1;\n```', { id: 'code-1' });
    const failed = message('assistant', 'oops', { id: 'fail-1', error: true });
    const long = message('assistant', 'y'.repeat(1500), { id: 'long-1' });
    renderMessages(list, [code, failed, long]);

    (list.querySelector('.wc-code-copy') as HTMLButtonElement).click();
    expect(onCopyCode).toHaveBeenCalledWith('const x = 1;\n');

    (list.querySelector('.wc-retry-message') as HTMLButtonElement).click();
    expect(onRetry).toHaveBeenCalledWith('fail-1');

    (list.querySelector('.wc-more-toggle') as HTMLButtonElement).click();
    expect(onToggleMore).toHaveBeenCalledWith('long-1');
  });
});
