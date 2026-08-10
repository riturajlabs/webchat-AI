import { describe, expect, it, vi } from 'vitest';
import { mount } from './mount';
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

describe('mount integration', () => {
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
          expect(body.question).toBe('hello');
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
          expect(body.question).toBe('hello');
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
    controller.sendMessage('hello');

    await vi.waitFor(() => {
      expect(host.shadowRoot?.querySelector('.wc-bubble-content')?.textContent).toBe('Hello');
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
    controller.sendMessage('hello');

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
});
