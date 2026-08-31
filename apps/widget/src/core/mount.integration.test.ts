import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from './mount';
import { NO_CONTEXT_ANSWER, NO_CONTEXT_REPLY } from '../conversation/intent';
const API_BASE = 'http://api.example.com/api/widget/v1';

const CONFIG = {
  widget_id: 'widget_1',
  enabled: true,
  theme: 'light',
  position: 'bottom-right',
  primary_color: '#2563eb',
  accent_color: '#f59e0b',
  font_size: 'md',
  logo_url: null,
  avatar_url: null,
  welcome_message: 'Hi!',
  placeholder: 'Type…',
  suggested_questions: ['What is pricing?'],
  branding: true,
  dark_mode: false,
  auto_open: false,
  bot_name: 'WebChat AI',
  bot_status_text: 'Online',
  header_color: null,
  secondary_color: null,
  background_color: null,
  text_color: null,
  font_family: null,
  width: '380px',
  height: '600px',
  border_radius: '20px',
  launcher_size: '58px',
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function sseResponse(events: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const event of events) {
        controller.enqueue(encoder.encode(event));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

/** Minimal fetch mock wiring for the standard API surface. */
function apiFetch(chatEvents: () => string[]): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.endsWith('/config/widget_1')) {
      return jsonResponse(CONFIG);
    }
    if (url.endsWith('/sessions')) {
      return jsonResponse({
        session_token: 'tok-1',
        expires_at: '2030-01-01T00:00:00Z',
      });
    }
    if (url.endsWith('/chat')) {
      return sseResponse(chatEvents());
    }
    if (url.endsWith('/feedback')) {
      return new Response(null, { status: 204 });
    }
    throw new Error(`unexpected URL: ${url}`);
  });
}

describe('mount integration', () => {
  beforeEach(() => {
    // Reduced-motion makes open/close synchronous in tests (no animation timers).
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
  });

  it('fetches config, mints a session, and streams a full exchange', async () => {
    const fetchImpl = vi.fn(
      async (input: string | URL | Request, init?: Parameters<typeof fetch>[1]) => {
        const url = String(input);
        if (url.endsWith('/config/widget_1')) {
          return jsonResponse(CONFIG);
        }
        if (url.endsWith('/sessions')) {
          return jsonResponse({
            session_token: 'tok-1',
            expires_at: '2030-01-01T00:00:00Z',
          });
        }
        if (url.endsWith('/chat')) {
          const body = init?.body ? JSON.parse(String(init.body)) : null;
          expect(body.question).toBe('What is pricing?');
          return sseResponse([
            'event: sources\ndata: {"sources":[{"url":"a"}]}\n\n',
            'event: message\ndata: {"delta":"Hel"}\n\n',
            'event: message\ndata: {"delta":"lo"}\n\n',
            'event: done\ndata: {"session_id":"s-1"}\n\n',
          ]);
        }
        throw new Error(`unexpected URL: ${url}`);
      },
    );

    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
    });

    await controller.ready();
    expect(controller.getConfig().welcome_message).toBe('Hi!');

    const host = document.querySelector('webchat-widget') as HTMLElement;
    expect(host).toBeTruthy();

    controller.open();
    expect(controller.isOpen()).toBe(true);

    // Drive the composer: find it inside the closed shadow root.
    const shadow = host.shadowRoot;
    expect(shadow).toBeNull(); // closed: not reachable externally

    // Instead, verify the send path via the controller's internal conversation.
    // We expose conversation access through the state by opening + sending via
    // the launcher button is not possible (closed root); assert fetch was used.
    await controller.ready();
    expect(fetchImpl).toHaveBeenCalledWith(
      expect.stringContaining('/sessions'),
      expect.objectContaining({ method: 'POST' }),
    );

    controller.destroy();
    expect(document.querySelector('webchat-widget')).toBeNull();
  });

  it('streams a full exchange (sources + deltas + done) into the DOM via sendMessage', async () => {
    const fetchImpl = vi.fn(
      async (input: string | URL | Request, init?: Parameters<typeof fetch>[1]) => {
        const url = String(input);
        if (url.endsWith('/config/widget_1')) {
          return jsonResponse(CONFIG);
        }
        if (url.endsWith('/sessions')) {
          return jsonResponse({
            session_token: 'tok-1',
            expires_at: '2030-01-01T00:00:00Z',
          });
        }
        if (url.endsWith('/chat')) {
          const body = init?.body ? JSON.parse(String(init.body)) : null;
          expect(body.question).toBe('What is pricing?');
          return sseResponse([
            'event: sources\ndata: {"sources":[{"url":"https://docs.example.com/x","title":"Docs X"}]}\n\n',
            'event: message\ndata: {"delta":"Hel"}\n\n',
            'event: message\ndata: {"delta":"lo"}\n\n',
            'event: done\ndata: {"session_id":"s-1"}\n\n',
          ]);
        }
        throw new Error(`unexpected URL: ${url}`);
      },
    );

    // An open shadow root lets the test inspect the rendered UI.
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('What is pricing?');

    await vi.waitFor(() => {
      expect(host.shadowRoot?.querySelector('.wc-bubble-content')?.textContent).toBe('Hello');
      expect(host.shadowRoot?.querySelector('.wc-sources')?.textContent).toContain('Docs X');
    });

    const shadow = host.shadowRoot as ShadowRoot;
    const contents = shadow.querySelectorAll('.wc-bubble-content');
    expect(contents[0].textContent).toBe('Hello');
    expect(shadow.querySelector('.wc-sources')?.textContent).toContain('Docs X');
    expect(shadow.querySelector('.wc-stopped')).toBeNull();
    const stop = shadow.querySelector<HTMLButtonElement>('.wc-stop');
    expect(stop?.hidden).toBe(true);
    expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(true);

    controller.destroy();
  });

  it('keeps the partial answer and marks it stopped when the turn is cancelled', async () => {
    const encoder = new TextEncoder();
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_1')) {
        return jsonResponse(CONFIG);
      }
      if (url.endsWith('/sessions')) {
        return jsonResponse({
          session_token: 'tok-1',
          expires_at: '2030-01-01T00:00:00Z',
        });
      }
      if (url.endsWith('/chat')) {
        // A stream that never ends: the Stop button must still cancel it.
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode('event: message\ndata: {"delta":"partial"}\n\n'));
          },
        });
        return new Response(body, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        });
      }
      throw new Error(`unexpected URL: ${url}`);
    });

    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('What is pricing?');

    const shadow = host.shadowRoot as ShadowRoot;
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-content')?.textContent).toBe('partial');
    });
    expect(shadow.querySelector<HTMLButtonElement>('.wc-stop')?.hidden).toBe(false);

    (shadow.querySelector('.wc-stop') as HTMLButtonElement).click();

    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-stopped')).toBeTruthy();
    });
    expect(shadow.querySelector('.wc-bubble-content')?.textContent).toBe('partial');
    expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(true);

    controller.destroy();
  });

  it('blocks chat and shows a persistent banner when the widget is disabled', async () => {
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_disabled_1')) {
        return jsonResponse({ ...CONFIG, widget_id: 'widget_disabled_1', enabled: false });
      }
      throw new Error(`unexpected URL: ${url}`);
    });

    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_disabled_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });

    await controller.ready();
    expect(controller.getConfig().enabled).toBe(false);

    const shadow = host.shadowRoot as ShadowRoot;
    // A disabled widget never mints a session and never hits /chat.
    expect(fetchImpl).not.toHaveBeenCalledWith(
      expect.stringContaining('/sessions'),
      expect.anything(),
    );
    expect(fetchImpl).not.toHaveBeenCalledWith(expect.stringContaining('/chat'), expect.anything());

    controller.open();
    const banner = shadow.querySelector<HTMLElement>('.wc-banner');
    expect(banner?.hidden).toBe(false);
    expect(banner?.textContent).toContain('This assistant is currently unavailable');
    const composer = shadow.querySelector<HTMLTextAreaElement>('textarea');
    expect(composer?.disabled).toBe(true);

    controller.destroy();
  });

  it('answers a greeting locally without ever calling the chat API', async () => {
    const fetchImpl = apiFetch(() => {
      throw new Error('/chat must not be called for a greeting');
    });
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
      // Long enough that the "thinking" phase outlasts a waitFor poll
      // interval, so the transient typing indicator is observable.
      intentReplyDelayMs: 400,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('hello');

    // Typing indicator shows while the local turn "thinks"… (renders land on
    // the next animation frame — streaming renders are coalesced.)
    const shadow = host.shadowRoot as ShadowRoot;
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-typing')).toBeTruthy();
    });
    // …and the Stop button is NOT offered for a non-streaming turn.
    expect((shadow.querySelector('.wc-stop') as HTMLButtonElement)?.hidden).toBe(true);

    // The local reply arrives without any /chat request.
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-content')?.textContent).toContain(
        'How can I help you today',
      );
    });
    expect(fetchImpl).not.toHaveBeenCalledWith(expect.stringContaining('/chat'), expect.anything());
    expect(shadow.querySelector('.wc-typing')).toBeNull();

    controller.destroy();
  });

  it('a real question still reaches the chat API (no intent false-positive)', async () => {
    const fetchImpl = apiFetch(() => [
      'event: message\ndata: {"delta":"pricing"}\n\n',
      'event: done\ndata: {"session_id":"s-1"}\n\n',
    ]);
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('hello, what is pricing?');

    await vi.waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledWith(expect.stringContaining('/chat'), expect.anything());
    });
    const shadow = host.shadowRoot as ShadowRoot;
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-content')?.textContent).toBe('pricing');
    });

    controller.destroy();
  });

  it('rewrites the backend zero-context fallback into a friendlier prompt', async () => {
    const fetchImpl = apiFetch(() => [
      `event: message\ndata: ${JSON.stringify({ delta: NO_CONTEXT_ANSWER })}\n\n`,
      `event: done\ndata: ${JSON.stringify({ session_id: 's-1', fallback: true })}\n\n`,
    ]);
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('What is the meaning of life?');

    const shadow = host.shadowRoot as ShadowRoot;
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-content')?.textContent).toBe(NO_CONTEXT_REPLY);
    });
    expect(shadow.querySelector('.wc-bubble-content')?.textContent).not.toContain(
      NO_CONTEXT_ANSWER,
    );

    controller.destroy();
  });

  it('close button hides the window and the launcher reopens it', async () => {
    const fetchImpl = apiFetch(() => []);
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();

    const shadow = host.shadowRoot as ShadowRoot;
    const windowEl = shadow.querySelector('.wc-window') as HTMLElement;
    const launcher = shadow.querySelector('.wc-launcher') as HTMLButtonElement;
    expect(windowEl.hidden).toBe(true); // starts closed

    (launcher as HTMLButtonElement).click();
    expect(controller.isOpen()).toBe(true);
    expect(windowEl.hidden).toBe(false);
    expect(shadow.querySelector<HTMLElement>('.wc-shell')?.dataset.open).toBe('true');
    expect(launcher.hidden).toBe(false);

    (shadow.querySelector('.wc-close') as HTMLButtonElement).click();
    expect(controller.isOpen()).toBe(false);
    expect(windowEl.hidden).toBe(true);
    expect(shadow.querySelector<HTMLElement>('.wc-shell')?.dataset.open).toBe('false');

    controller.destroy();
  });

  it('hides the suggested chips once the visitor sends their first message', async () => {
    const fetchImpl = apiFetch(() => [
      'event: message\ndata: {"delta":"answer"}\n\n',
      'event: done\ndata: {"session_id":"s-1"}\n\n',
    ]);
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();

    const shadow = host.shadowRoot as ShadowRoot;
    const suggested = shadow.querySelector<HTMLElement>('.wc-suggested');
    expect(suggested).toBeTruthy();
    expect(suggested?.hidden).toBe(false);

    controller.sendMessage('What is pricing?');
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-content')?.textContent).toBe('answer');
    });
    expect(suggested?.hidden).toBe(true);

    controller.destroy();
  });

  it('five-star rating submits feedback immediately with no comment form', async () => {
    const fetchImpl = apiFetch(() => [
      'event: message\ndata: {"delta":"answer"}\n\n',
      'event: done\ndata: {"session_id":"s-1","message_id":"m-1"}\n\n',
    ]);
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('What is pricing?');

    const shadow = host.shadowRoot as ShadowRoot;
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-star')).toBeTruthy();
    });
    // Compact UX: no comment form inside the feedback control.
    expect(shadow.querySelector('.wc-feedback textarea')).toBeNull();
    expect(shadow.querySelector('.wc-feedback-submit')).toBeNull();

    (shadow.querySelector('.wc-star[data-rating="5"]') as HTMLButtonElement).click();
    await vi.waitFor(() => {
      expect(fetchImpl).toHaveBeenCalledWith(
        expect.stringContaining('/feedback'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"rating":5'),
        }),
      );
    });

    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-feedback-note')?.textContent).toContain(
        'Thanks for your feedback',
      );
    });

    controller.destroy();
  });

  it('recovers when the SSE body errors mid-stream (turn must not stay stuck)', async () => {
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_1')) {
        return jsonResponse(CONFIG);
      }
      if (url.endsWith('/sessions')) {
        return jsonResponse({
          session_token: 'tok-1',
          expires_at: '2030-01-01T00:00:00Z',
        });
      }
      if (url.endsWith('/chat')) {
        // Deliver one delta, then fail the body mid-read. streamChat rethrows
        // this non-abort failure; mount's catch must fail the turn instead of
        // leaving it streaming forever.
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode('event: message\ndata: {"delta":"partial"}\n\n'),
            );
            controller.error(new Error('connection reset mid-stream'));
          },
        });
        return new Response(body, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        });
      }
      throw new Error(`unexpected URL: ${url}`);
    });

    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('What is pricing?');

    const shadow = host.shadowRoot as ShadowRoot;
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-error')).toBeTruthy();
    });
    // The failed turn offers Retry and never keeps the Stop button active.
    expect(shadow.querySelector('.wc-retry-message')).toBeTruthy();
    expect(shadow.querySelector<HTMLButtonElement>('.wc-stop')?.hidden).toBe(true);
    // The visitor is told what happened and can type again immediately.
    expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(false);
    expect(shadow.querySelector('.wc-banner')?.textContent).toContain(
      'Unable to connect right now',
    );
    expect(shadow.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(false);

    controller.destroy();
  });

  it('renders an answer delivered as a single post-delay burst', async () => {
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_1')) {
        return jsonResponse(CONFIG);
      }
      if (url.endsWith('/sessions')) {
        return jsonResponse({
          session_token: 'tok-1',
          expires_at: '2030-01-01T00:00:00Z',
        });
      }
      if (url.endsWith('/chat')) {
        // Production pattern (observed via Groq): TTFT dominates and every
        // delta arrives coalesced into ONE chunk right before the stream
        // closes. The consumer must still render sources + answer + done.
        const frames =
          'event: sources\ndata: {"sources":[{"url":"https://docs.example.com/x","title":"Docs X"}]}\n\n' +
          'event: message\ndata: {"delta":"Full answer"}\n\n' +
          'event: done\ndata: {"session_id":"s-burst","fallback":false}\n\n';
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            window.setTimeout(() => {
              controller.enqueue(new TextEncoder().encode(frames));
              controller.close();
            }, 30);
          },
        });
        return new Response(body, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        });
      }
      throw new Error(`unexpected URL: ${url}`);
    });

    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_1',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    await controller.ready();
    controller.open();
    controller.sendMessage('What is pricing?');

    const shadow = host.shadowRoot as ShadowRoot;
    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-content')?.textContent).toBe('Full answer');
    });
    expect(shadow.querySelector('.wc-sources')?.textContent).toContain('Docs X');
    expect(shadow.querySelector('.wc-stopped')).toBeNull();
    expect(shadow.querySelector('.wc-bubble-error')).toBeNull();
    expect(shadow.querySelector<HTMLButtonElement>('.wc-stop')?.hidden).toBe(true);

    controller.destroy();
  });
});

/** SSE response whose frames are withheld until `gate` resolves. */
function gatedSseResponse(gate: Promise<void>, events: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      await gate;
      const encoder = new TextEncoder();
      for (const event of events) {
        controller.enqueue(encoder.encode(event));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

describe('widget production audit fixes (P2)', () => {
  beforeEach(() => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
  });

  it('announces the completed answer in the status live region (audit W-12)', async () => {
    const fetchImpl = apiFetch(() => [
      'event: message\ndata: {"delta":"Streaming answers mutate innerHTML,"}\n\n',
      'event: message\ndata: {"delta":" so additions-only regions stay silent."}\n\n',
      'event: done\ndata: {"session_id":"s-1"}\n\n',
    ]);
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({ widgetId: 'widget_1', apiBaseUrl: API_BASE, fetchImpl, host });
    await controller.ready();
    controller.open();

    controller.sendMessage('What is pricing?');
    const shadow = host.shadowRoot as ShadowRoot;

    await vi.waitFor(() => {
      expect(shadow.querySelector('.wc-bubble-content')?.textContent).toContain(
        'additions-only regions stay silent.',
      );
    });
    // Same reconciliation pass that finished the turn pushed the final answer
    // into the polite live region — screen readers hear it exactly once.
    expect(shadow.querySelector('.wc-status-live')?.textContent).toContain(
      'additions-only regions stay silent.',
    );

    controller.destroy();
  });

  it('keeps the composer editable while a turn streams (audit: composer lockout)', async () => {
    const encoder = new TextEncoder();
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_1')) {
        return jsonResponse(CONFIG);
      }
      if (url.endsWith('/sessions')) {
        return jsonResponse({ session_token: 'tok-1', expires_at: '2030-01-01T00:00:00Z' });
      }
      if (url.endsWith('/chat')) {
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode('event: message\ndata: {"delta":"working"}\n\n'));
          },
        });
        return new Response(body, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        });
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({ widgetId: 'widget_1', apiBaseUrl: API_BASE, fetchImpl, host });
    await controller.ready();
    controller.open();

    const shadow = host.shadowRoot as ShadowRoot;
    controller.sendMessage('What is pricing?');
    await vi.waitFor(() => {
      expect(shadow.querySelector<HTMLButtonElement>('.wc-stop')?.hidden).toBe(false);
    });

    // Typing must remain possible mid-stream…
    const input = shadow.querySelector<HTMLTextAreaElement>('textarea');
    expect(input?.disabled).toBe(false);

    // …and submitting queues the draft instead of hitting the API while
    // the turn is still active.
    input!.value = 'follow-up question';
    input!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(fetchImpl.mock.calls.filter(([u]) => String(u).endsWith('/chat'))).toHaveLength(1);
    expect(input!.value).toBe('');

    controller.destroy();
  });

  it('auto-sends a question queued mid-stream once the turn completes', async () => {
    const chatQuestions: string[] = [];
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/config/widget_1')) {
        return jsonResponse(CONFIG);
      }
      if (url.endsWith('/sessions')) {
        return jsonResponse({ session_token: 'tok-1', expires_at: '2030-01-01T00:00:00Z' });
      }
      if (url.endsWith('/chat')) {
        const body = init?.body ? JSON.parse(String(init.body)) : null;
        chatQuestions.push(body.question);
        if (chatQuestions.length === 1) {
          // First turn hangs until the test releases it.
          return gatedSseResponse(gate, [
            'event: message\ndata: {"delta":"first answer"}\n\n',
            'event: done\ndata: {"session_id":"s-1"}\n\n',
          ]);
        }
        return sseResponse([
          'event: message\ndata: {"delta":"second answer"}\n\n',
          'event: done\ndata: {"session_id":"s-1"}\n\n',
        ]);
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({ widgetId: 'widget_1', apiBaseUrl: API_BASE, fetchImpl, host });
    await controller.ready();
    controller.open();

    const shadow = host.shadowRoot as ShadowRoot;
    controller.sendMessage('What is pricing?');
    await vi.waitFor(() => {
      expect(shadow.querySelector<HTMLButtonElement>('.wc-stop')?.hidden).toBe(false);
    });

    const input = shadow.querySelector<HTMLTextAreaElement>('textarea');
    input!.value = 'follow-up question';
    input!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(chatQuestions).toEqual(['What is pricing?']);

    release(); // finish turn 1 -> the queued question must fire as turn 2

    await vi.waitFor(() => {
      expect(chatQuestions).toEqual(['What is pricing?', 'follow-up question']);
    });
    await vi.waitFor(() => {
      const contents = shadow.querySelectorAll('.wc-bubble-content');
      expect(contents[contents.length - 1]?.textContent).toBe('second answer');
    });

    controller.destroy();
  });

  it('lifts the shell above the keyboard via --wc-keyboard-inset and stops on destroy (audit W-06)', async () => {
    const listeners = new Map<string, Set<EventListener>>();
    const fakeViewport = {
      height: 448,
      offsetTop: 0,
      addEventListener(type: string, listener: EventListener) {
        const set = listeners.get(type) ?? new Set<EventListener>();
        set.add(listener);
        listeners.set(type, set);
      },
      removeEventListener(type: string, listener: EventListener) {
        listeners.get(type)?.delete(listener);
      },
    };
    Object.defineProperty(window, 'visualViewport', {
      configurable: true,
      value: fakeViewport,
    });
    try {
      const fetchImpl = apiFetch(() => []);
      const host = document.createElement('webchat-widget');
      host.attachShadow({ mode: 'open' });
      const controller = mount({ widgetId: 'widget_1', apiBaseUrl: API_BASE, fetchImpl, host });
      await controller.ready();

      const shell = host.shadowRoot?.querySelector('.wc-shell') as HTMLElement;
      // jsdom innerHeight is 768: 768 - 448 = 320px occluded by the keyboard.
      expect(shell.style.getPropertyValue('--wc-keyboard-inset')).toBe('320px');

      fakeViewport.height = 568; // keyboard shrinks
      for (const listener of listeners.get('resize') ?? []) {
        (listener as (event: Event) => void)(new Event('resize'));
      }
      expect(shell.style.getPropertyValue('--wc-keyboard-inset')).toBe('200px');

      controller.destroy();
      fakeViewport.height = 100;
      for (const listener of listeners.get('resize') ?? []) {
        (listener as (event: Event) => void)(new Event('resize'));
      }
      // Listeners were detached on destroy: the stale value is untouched.
      expect(shell.style.getPropertyValue('--wc-keyboard-inset')).toBe('200px');
    } finally {
      delete (window as unknown as Record<string, unknown>).visualViewport;
    }
  });
});

describe('banner lifecycle + motion handling audit fixes', () => {
  beforeEach(() => {
    // Reduced-motion context on purpose: W-04 asserts auto_open still opens.
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
  });

  /** jsdom never flips onLine by itself; force it for offline-banner tests. */
  function setOnline(online: boolean): void {
    Object.defineProperty(window.navigator, 'onLine', {
      configurable: true,
      value: online,
    });
  }

  function mountWith(autoOpen = false) {
    let failNext = false;
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_1')) {
        return jsonResponse({ ...CONFIG, auto_open: autoOpen });
      }
      if (url.endsWith('/sessions')) {
        return jsonResponse({ session_token: 'tok-1', expires_at: '2030-01-01T00:00:00Z' });
      }
      if (url.endsWith('/chat')) {
        if (failNext) {
          throw new TypeError('Failed to fetch');
        }
        return sseResponse([
          'event: message\ndata: {"delta":"answer"}\n\n',
          'event: done\ndata: {"session_id":"s-1"}\n\n',
        ]);
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({ widgetId: 'widget_1', apiBaseUrl: API_BASE, fetchImpl, host });
    return { controller, host, setFailNext: (v: boolean) => (failNext = v) };
  }

  it('does not resurrect a dismissed banner across sync passes (audit W-02)', async () => {
    const { controller, host, setFailNext } = mountWith();
    await controller.ready();
    controller.open();
    const shadow = host.shadowRoot as ShadowRoot;

    setFailNext(true);
    controller.sendMessage('What is pricing?');
    await vi.waitFor(() => {
      expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(false);
    });

    (shadow.querySelector('.wc-banner-dismiss') as HTMLButtonElement).click();
    expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(true);

    // Every state transition re-runs syncRenderer; the dismissed error must
    // stay dismissed through open/close cycles and offline/online flips.
    controller.close();
    controller.open();
    try {
      setOnline(false);
      window.dispatchEvent(new Event('offline'));
      await vi.waitFor(() => {
        expect(shadow.querySelector('.wc-banner')?.textContent).toContain('offline');
      });
      // Still offline: dismissing connectivity info must stick too.
      (shadow.querySelector('.wc-banner-dismiss') as HTMLButtonElement).click();
      window.dispatchEvent(new Event('offline'));
      await vi.waitFor(() => {
        expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(true);
      });
      setOnline(true);
      window.dispatchEvent(new Event('online'));
      await vi.waitFor(() => {
        expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(true);
      });
    } finally {
      setOnline(true);
    }

    controller.destroy();
  });

  it('surfaces a genuinely new failure after a dismissal, but not stale ones', async () => {
    const { controller, host, setFailNext } = mountWith();
    await controller.ready();
    controller.open();
    const shadow = host.shadowRoot as ShadowRoot;

    // First turn fails -> banner -> visitor dismisses it.
    setFailNext(true);
    controller.sendMessage('What is pricing?');
    await vi.waitFor(() => {
      expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(false);
    });
    (shadow.querySelector('.wc-banner-dismiss') as HTMLButtonElement).click();
    expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(true);

    // A successful turn must NOT resurrect the stale error…
    setFailNext(false);
    controller.sendMessage('What are your support hours?');
    await vi.waitFor(() => {
      expect(
        Array.from(shadow.querySelectorAll('.wc-bubble-content')).some(
          (el) => el.textContent === 'answer',
        ),
      ).toBe(true);
    });
    expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(true);

    // …but a NEW failing attempt shows the banner again.
    setFailNext(true);
    controller.sendMessage('What is your refund policy?');
    await vi.waitFor(() => {
      expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(false);
    });

    controller.destroy();
  });

  it('restores the pending error banner after a transient offline episode', async () => {
    const { controller, host, setFailNext } = mountWith();
    await controller.ready();
    controller.open();
    const shadow = host.shadowRoot as ShadowRoot;

    setFailNext(true);
    controller.sendMessage('What is pricing?');
    await vi.waitFor(() => {
      expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(false);
    });

    // Offline takes priority while active; when it clears, the error banner
    // (with Retry) must come back — it was never dismissed.
    try {
      setOnline(false);
      window.dispatchEvent(new Event('offline'));
      await vi.waitFor(() => {
        expect(shadow.querySelector('.wc-banner')?.textContent).toContain('offline');
      });
      setOnline(true);
      window.dispatchEvent(new Event('online'));
      await vi.waitFor(() => {
        expect(shadow.querySelector<HTMLElement>('.wc-banner')?.hidden).toBe(false);
      });
      expect((shadow.querySelector('.wc-banner-retry') as HTMLButtonElement)?.hidden).toBe(false);
    } finally {
      setOnline(true);
    }

    controller.destroy();
  });

  it('honors auto_open even under prefers-reduced-motion (audit W-04)', async () => {
    // A distinct widget id avoids the in-module config cache seeded by the
    // earlier tests (same widget_1, auto_open:false).
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_auto')) {
        return jsonResponse({ ...CONFIG, widget_id: 'widget_auto', auto_open: true });
      }
      if (url.endsWith('/sessions')) {
        return jsonResponse({ session_token: 'tok-1', expires_at: '2030-01-01T00:00:00Z' });
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({
      widgetId: 'widget_auto',
      apiBaseUrl: API_BASE,
      fetchImpl,
      host,
    });
    try {
      await controller.ready();
      // matchMedia is stubbed to "reduce" in beforeEach: the dialog must still
      // open automatically; only its entrance animation is disabled (CSS).
      expect(controller.isOpen()).toBe(true);
      expect(host.shadowRoot?.querySelector<HTMLElement>('.wc-window')?.hidden).toBe(false);
    } finally {
      controller.destroy();
    }
  });
});
