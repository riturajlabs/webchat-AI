import { describe, expect, it } from 'vitest';
import {
  DEFAULT_ACCENT_COLOR,
  DEFAULT_PRIMARY_COLOR,
  THEME_PRESETS,
  getThemePreset,
  readableText,
  relativeLuminance,
  resolveTheme,
} from './index';

describe('theme presets', () => {
  it('exposes the curated presets with unique ids', () => {
    expect(THEME_PRESETS).toHaveLength(10);
    const ids = THEME_PRESETS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(THEME_PRESETS.map((t) => t.id)).toEqual([
      'whatsapp-classic',
      'ios-native',
      'enterprise-slate',
      'ocean-blue',
      'midnight-dark',
      'emerald-support',
      'purple-ai',
      'minimal-white',
      'sunset',
      'modern-gradient',
    ]);
  });

  it('every preset ships light and dark token sets with the required fields', () => {
    const required = [
      'primary',
      'accent',
      'header',
      'headerText',
      'surface',
      'surfaceElevated',
      'text',
      'muted',
      'border',
      'assistantBubble',
      'userBubble',
      'userText',
      'inputBg',
      'scrollbarThumb',
      'scrollbarTrack',
    ];
    for (const preset of THEME_PRESETS) {
      for (const mode of ['light', 'dark'] as const) {
        for (const field of required) {
          expect(typeof preset[mode][field], `${preset.id}.${mode}.${field}`).toBe('string');
        }
      }
    }
  });

  it('only modern-gradient renders a gradient header', () => {
    expect(getThemePreset('modern-gradient')?.headerGradient).toBe(true);
    expect(getThemePreset('ocean-blue')?.headerGradient).toBe(false);
  });
});

describe('readableText / relativeLuminance', () => {
  it('returns white text on dark backgrounds and dark text on light ones', () => {
    expect(readableText('#000000')).toBe('#ffffff');
    expect(readableText('#1e3a8a')).toBe('#ffffff');
    expect(readableText('#ffffff')).toBe('#18181b');
    expect(readableText('#f4f4f5')).toBe('#18181b');
  });

  it('handles 3-digit and invalid hex gracefully', () => {
    expect(relativeLuminance('#fff')).toBeGreaterThan(0.5);
    expect(relativeLuminance('garbage')).toBeGreaterThan(0.5);
  });
});

describe('resolveTheme', () => {
  it('applies preset tokens by default when a preset is selected', () => {
    const resolved = resolveTheme({ theme_preset: 'emerald-support' }, false);
    expect(resolved.primary).toBe('#059669');
    expect(resolved.surface).toBe('#ffffff');
    expect(resolved.header).toBe('#064e3b');
    expect(resolved.userBubble).toBe('#047857');
  });

  it('switches to the dark token set in dark mode', () => {
    const light = resolveTheme({ theme_preset: 'emerald-support' }, false);
    const dark = resolveTheme({ theme_preset: 'emerald-support' }, true);
    expect(light.primary).toBe('#059669');
    expect(dark.primary).toBe('#059669');
    expect(dark.surface).toBe('#06231c');
  });

  it('treats default-colored values as not-overridden so the preset palette wins', () => {
    const resolved = resolveTheme(
      { theme_preset: 'ocean-blue', primary_color: DEFAULT_PRIMARY_COLOR },
      false,
    );
    expect(resolved.primary).toBe('#0284c7');
  });

  it('lets explicitly customized colors override the preset palette', () => {
    const resolved = resolveTheme(
      { theme_preset: 'ocean-blue', primary_color: '#c026d3', accent_color: '#10b981' },
      false,
    );
    expect(resolved.primary).toBe('#c026d3');
    expect(resolved.accent).toBe('#10b981');
  });

  it('always applies direct overrides (header/background/text)', () => {
    const resolved = resolveTheme(
      {
        theme_preset: 'emerald-support',
        header_color: '#111111',
        background_color: '#fefefe',
        text_color: '#101010',
      },
      true,
    );
    expect(resolved.header).toBe('#111111');
    expect(resolved.headerText).toBe('#ffffff');
    expect(resolved.surface).toBe('#fefefe');
    expect(resolved.surfaceElevated).toBe('#fefefe');
    expect(resolved.text).toBe('#101010');
  });

  it('renders a gradient header when no preset is selected', () => {
    const resolved = resolveTheme({}, false);
    expect(resolved.header).toBe(
      `linear-gradient(135deg, ${DEFAULT_PRIMARY_COLOR}, ${DEFAULT_ACCENT_COLOR})`,
    );
    expect(resolved.headerText).toBe('#ffffff');
    expect(resolved.userBubble).toBe(DEFAULT_PRIMARY_COLOR);
  });

  it('supports secondary_color independently of accent', () => {
    const resolved = resolveTheme({ secondary_color: '#f97316' }, false);
    expect(resolved.secondary).toBe('#f97316');
    expect(resolved.accent).toBe(DEFAULT_ACCENT_COLOR);
    expect(resolved.header).toBe(`linear-gradient(135deg, ${DEFAULT_PRIMARY_COLOR}, #f97316)`);
  });

  it('uses preset secondary fallback (accent) and dark-mode surface', () => {
    const resolved = resolveTheme({ theme_preset: 'purple-ai' }, true);
    expect(resolved.secondary).toBe(resolved.accent);
    expect(resolved.surface).toBe('#140b2e');
  });
});

describe('theme readability (no unreadable UI in any preset)', () => {
  function contrast(a: string, b: string): number {
    const [la, lb] = [relativeLuminance(a), relativeLuminance(b)];
    const hi = Math.max(la, lb);
    const lo = Math.min(la, lb);
    return (hi + 0.05) / (lo + 0.05);
  }

  for (const preset of THEME_PRESETS) {
    for (const mode of ['light', 'dark'] as const) {
      it(`${preset.id} (${mode}) stays readable`, () => {
        const t = preset[mode];
        const label = (subject: string) => `${preset.id}.${mode} ${subject}`;
        expect(contrast(t.text, t.surface), label('body text on surface')).toBeGreaterThanOrEqual(
          4.5,
        );
        expect(contrast(t.muted, t.surface), label('muted text on surface')).toBeGreaterThanOrEqual(
          3,
        );
        expect(
          contrast(t.muted, t.inputBg),
          label('input placeholder on input bg'),
        ).toBeGreaterThanOrEqual(3);
        expect(
          contrast(t.text, t.assistantBubble),
          label('assistant text on bubble'),
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          contrast(t.userText, t.userBubble),
          label('user text on bubble'),
        ).toBeGreaterThanOrEqual(4.5);
        expect(contrast(t.primary, t.surface), label('link on surface')).toBeGreaterThanOrEqual(3);
        expect(
          contrast(t.primary, t.assistantBubble),
          label('link on assistant bubble'),
        ).toBeGreaterThanOrEqual(3);
        if (preset.headerGradient) {
          expect(
            contrast(t.headerText, t.primary),
            label('header text on gradient primary'),
          ).toBeGreaterThanOrEqual(3);
          expect(
            contrast(t.headerText, t.accent),
            label('header text on gradient accent'),
          ).toBeGreaterThanOrEqual(3);
        } else {
          expect(
            contrast(t.headerText, t.header),
            label('header text on header'),
          ).toBeGreaterThanOrEqual(4.5);
        }
        expect(
          contrast(readableText(t.primary), t.primary),
          label('launcher/send icon on primary'),
        ).toBeGreaterThanOrEqual(3);
        expect(
          contrast(readableText(t.accent), t.accent),
          label('send icon on accent'),
        ).toBeGreaterThanOrEqual(3);
      });
    }
  }
});
