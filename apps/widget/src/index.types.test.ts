import { describe, expect, expectTypeOf, it, vi } from 'vitest';
import { init, mount, type WidgetController } from './index';
import type {
  WidgetOptions,
  WidgetOverride,
  WidgetPosition,
  WidgetPublicConfig,
} from './config/types';
import type { SessionManager } from './core/session';
import type { ChatSource } from './stream/chat';

// Compile-time surface checks for the published SDK types (audit W-21). The
// runtime assertions keep vitest happy; the real value is that `tsc --noEmit`
// (part of `npm run build`) fails if any export drifts.

describe('public SDK types (audit W-21)', () => {
  it('mount/init return a fully typed controller', () => {
    // matchMedia is unavailable in jsdom; the SDK guards for it, but stub it
    // so the real mount() call below stays on the well-trodden path.
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const options: WidgetOptions = { widgetId: 'widget_1' };
    expectTypeOf(mount(options)).toEqualTypeOf<WidgetController>();
    expectTypeOf(init(options)).toEqualTypeOf<WidgetController>();

    const controller = mount({ ...options, autoStart: false });
    try {
      expectTypeOf(controller.widgetId).toEqualTypeOf<string>();
      expectTypeOf(controller.apiBaseUrl).toEqualTypeOf<string>();
      expectTypeOf(controller.visitorId).toEqualTypeOf<string>();
      expectTypeOf(controller.session).toEqualTypeOf<SessionManager>();
      expectTypeOf(controller.getConfig()).toEqualTypeOf<WidgetPublicConfig>();
      expectTypeOf(controller.ready()).toEqualTypeOf<Promise<WidgetPublicConfig>>();
      expectTypeOf(controller.isOpen()).toEqualTypeOf<boolean>();
      expectTypeOf(controller.sendMessage).parameter(0).toEqualTypeOf<string>();
      expect(controller.widgetId).toBe('widget_1');
    } finally {
      controller.destroy();
    }
  });

  it('exposes the public config shape consumers render from', () => {
    expectTypeOf<WidgetPublicConfig['position']>().toEqualTypeOf<string>();
    expectTypeOf<WidgetPublicConfig['suggested_questions']>().toEqualTypeOf<string[]>();
    expectTypeOf<WidgetPublicConfig['header_color']>().toEqualTypeOf<string | null>();
    expectTypeOf<WidgetPublicConfig['auto_open']>().toEqualTypeOf<boolean>();
  });

  it('keeps the embed override position union narrow', () => {
    const valid: WidgetOverride = { position: 'bottom-left' };
    expectTypeOf<WidgetPosition>().toEqualTypeOf<'bottom-right' | 'bottom-left'>();

    // @ts-expect-error invalid positions are rejected at compile time
    const invalid: WidgetOverride = { position: 'top-center' };
    expect(valid).toBeTruthy();
    expect(invalid).toBeTruthy();
  });

  it('exports source/message payload types for event wiring', () => {
    const source: ChatSource = { url: 'https://example.com', title: 'Example' };
    expectTypeOf(source.url).toEqualTypeOf<string | undefined>();
    expect(source.title).toBe('Example');
  });
});
