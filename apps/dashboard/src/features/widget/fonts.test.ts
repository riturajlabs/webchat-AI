import { describe, expect, it } from 'vitest';
import { CURATED_FONTS, fontFamilyToKey, fontKeyToStack, loadPreviewFont } from './fonts';

describe('dashboard widget typography registry (CURATED_FONTS)', () => {
  it('contains exactly 10 curated fonts', () => {
    expect(CURATED_FONTS).toHaveLength(10);
    const keys = CURATED_FONTS.map((f) => f.key);
    expect(new Set(keys).size).toBe(10);
    const labels = CURATED_FONTS.map((f) => f.label);
    expect(new Set(labels).size).toBe(10);
  });

  it('configures system default font with null stack and stylesheetUrl', () => {
    const system = CURATED_FONTS.find((f) => f.key === 'system');
    expect(system).toBeDefined();
    expect(system?.label).toBe('System default');
    expect(system?.stack).toBeNull();
    expect(system?.stylesheetUrl).toBeNull();
  });

  it('configures all 9 web fonts with correct Google Fonts stylesheet URLs and weights', () => {
    const expectedWeights: Record<string, string> = {
      inter: 'wght@400;500;600',
      poppins: 'wght@400;500;600',
      nunito: 'wght@400;600;700',
      roboto: 'wght@400;500;700',
      'open-sans': 'wght@400;500;600;700',
      montserrat: 'wght@400;500;600;700',
      lato: 'wght@400;700',
      'playfair-display': 'wght@500;700',
      'space-grotesk': 'wght@500;700',
    };

    const webFonts = CURATED_FONTS.filter((f) => f.key !== 'system');
    expect(webFonts).toHaveLength(9);

    for (const font of webFonts) {
      expect(font.stylesheetUrl).toMatch(/^https:\/\/fonts\.googleapis\.com\/css2\?family=/);
      expect(font.stylesheetUrl).toContain('display=swap');
      const expected = expectedWeights[font.key];
      expect(expected).toBeDefined();
      expect(font.stylesheetUrl).toContain(expected);
      expect(font.stack).toBeTruthy();
    }
  });
});

describe('fontFamilyToKey', () => {
  it('maps null, undefined, and empty string to system', () => {
    expect(fontFamilyToKey(null)).toBe('system');
    expect(fontFamilyToKey(undefined)).toBe('system');
    expect(fontFamilyToKey('')).toBe('system');
  });

  it('maps explicit system keywords and system stack to system', () => {
    expect(fontFamilyToKey('system')).toBe('system');
    expect(fontFamilyToKey('system default')).toBe('system');
    expect(
      fontFamilyToKey(
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
      ),
    ).toBe('system');
  });

  it('does NOT confuse system font stack with Roboto', () => {
    const systemStack =
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
    expect(fontFamilyToKey(systemStack)).toBe('system');
  });

  it('maps each of the 9 web fonts by key, label, and full stack', () => {
    for (const font of CURATED_FONTS) {
      if (font.key === 'system') continue;
      expect(fontFamilyToKey(font.key)).toBe(font.key);
      expect(fontFamilyToKey(font.label)).toBe(font.key);
      expect(fontFamilyToKey(font.label.toLowerCase())).toBe(font.key);
      if (font.stack) {
        expect(fontFamilyToKey(font.stack)).toBe(font.key);
      }
    }
  });

  it('falls back to system for uncurated / arbitrary font families', () => {
    expect(fontFamilyToKey('Comic Sans MS')).toBe('system');
    expect(fontFamilyToKey('Papyrus')).toBe('system');
    expect(fontFamilyToKey('<script>evil</script>')).toBe('system');
  });
});

describe('fontKeyToStack', () => {
  it('returns null for system or unknown keys', () => {
    expect(fontKeyToStack('system')).toBeNull();
    expect(fontKeyToStack('unknown-key')).toBeNull();
  });

  it('returns stack for each curated web font', () => {
    expect(fontKeyToStack('inter')).toBe("'Inter', system-ui, -apple-system, sans-serif");
    expect(fontKeyToStack('roboto')).toBe("'Roboto', system-ui, -apple-system, sans-serif");
    expect(fontKeyToStack('playfair-display')).toBe("'Playfair Display', Georgia, serif");
  });
});

describe('loadPreviewFont', () => {
  it('does not inject link for system or null', () => {
    const countBefore = document.head.querySelectorAll('link[data-webchat-preview-font]').length;
    loadPreviewFont(null);
    loadPreviewFont('system');
    const countAfter = document.head.querySelectorAll('link[data-webchat-preview-font]').length;
    expect(countAfter).toBe(countBefore);
  });

  it('injects link for curated web font and deduplicates', () => {
    loadPreviewFont('Roboto');
    const links = document.head.querySelectorAll('link[data-webchat-preview-font="roboto"]');
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute('href')).toContain('Roboto');

    // Duplicate call should not add another link
    loadPreviewFont('roboto');
    const linksAfter = document.head.querySelectorAll('link[data-webchat-preview-font="roboto"]');
    expect(linksAfter).toHaveLength(1);
  });
});
