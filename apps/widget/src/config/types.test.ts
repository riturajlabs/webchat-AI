import { afterEach, describe, expect, it } from 'vitest';
import { resolveApiBaseUrl, sanitizeApiBaseUrl, normalizeConfig, DEFAULT_CONFIG } from './types';

const ENV_KEY = 'VITE_WIDGET_API_BASE_URL';

function setEnvBaseUrl(value: string | undefined): void {
  const env = (import.meta.env ?? {}) as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[ENV_KEY];
  } else {
    env[ENV_KEY] = value;
  }
}

afterEach(() => {
  setEnvBaseUrl(undefined);
});

describe('resolveApiBaseUrl', () => {
  it('appends the versioned path to a host-only base', () => {
    expect(resolveApiBaseUrl('https://api.example.com')).toBe(
      'https://api.example.com/api/widget/v1',
    );
  });

  it('keeps an already-versioned base unchanged', () => {
    expect(resolveApiBaseUrl('https://api.example.com/api/widget/v1')).toBe(
      'https://api.example.com/api/widget/v1',
    );
  });

  it('handles trailing slashes', () => {
    expect(resolveApiBaseUrl('https://api.example.com/api/widget/v1/')).toBe(
      'https://api.example.com/api/widget/v1',
    );
  });

  it('falls back to the same-origin base when no base is configured', () => {
    setEnvBaseUrl(undefined);
    expect(resolveApiBaseUrl(undefined)).toBe('/api/widget/v1');
  });

  it('uses the build-time env base when no explicit base is given', () => {
    setEnvBaseUrl('https://cdn.webchat-ai.example/api/widget/v1');
    expect(resolveApiBaseUrl(undefined)).toBe('https://cdn.webchat-ai.example/api/widget/v1');
  });

  it('resolves an empty explicit base to the same-origin base', () => {
    expect(resolveApiBaseUrl('')).toBe('/api/widget/v1');
  });
});

describe('sanitizeApiBaseUrl', () => {
  it('strips trailing slashes', () => {
    expect(sanitizeApiBaseUrl('https://api.example.com///')).toBe('https://api.example.com');
  });
});

describe('normalizeConfig', () => {
  it('fills every missing field from the safe defaults (older backend payloads)', () => {
    const config = normalizeConfig({ widget_id: 'w1', welcome_message: 'Hi!' });
    expect(config.welcome_message).toBe('Hi!');
    expect(config.bot_name).toBe(DEFAULT_CONFIG.bot_name);
    expect(config.width).toBe(DEFAULT_CONFIG.width);
    expect(config.height).toBe(DEFAULT_CONFIG.height);
    expect(config.border_radius).toBe(DEFAULT_CONFIG.border_radius);
    expect(config.launcher_size).toBe(DEFAULT_CONFIG.launcher_size);
    expect(config.bot_status_text).toBe(DEFAULT_CONFIG.bot_status_text);
    expect(config.header_color).toBeNull();
    expect(config.enabled).toBe(true);
  });

  it('keeps explicit overrides and a provided widget id', () => {
    const config = normalizeConfig({
      widget_id: 'w1',
      bot_name: 'Acme Support',
      width: '480px',
      primary_color: '#ff0000',
    });
    expect(config.bot_name).toBe('Acme Support');
    expect(config.width).toBe('480px');
    expect(config.primary_color).toBe('#ff0000');
    expect(config.widget_id).toBe('w1');
  });

  it('falls back to "unknown" when widget_id is missing', () => {
    expect(normalizeConfig({}).widget_id).toBe('unknown');
  });

  it('is a no-op for already-complete configs', () => {
    const full = normalizeConfig({ widget_id: 'w1', ...DEFAULT_CONFIG });
    expect(full).toEqual({ widget_id: 'w1', ...DEFAULT_CONFIG });
  });
});

describe('position validation (audit W-01)', () => {
  it('accepts the two supported positions', () => {
    expect(normalizeConfig({ widget_id: 'w', position: 'bottom-right' }).position).toBe(
      'bottom-right',
    );
    expect(normalizeConfig({ widget_id: 'w', position: 'bottom-left' }).position).toBe(
      'bottom-left',
    );
  });

  it('falls back to bottom-right for invalid positions instead of leaving the shell unpositioned', () => {
    expect(normalizeConfig({ widget_id: 'w', position: 'top-center' }).position).toBe(
      'bottom-right',
    );
    expect(normalizeConfig({ widget_id: 'w', position: 'right;position:fixed' }).position).toBe(
      'bottom-right',
    );
    expect(normalizeConfig({ widget_id: 'w', position: '' }).position).toBe('bottom-right');
  });
});

describe('dynamic style-input validation (audit W-23)', () => {
  it('keeps valid tenant customizations untouched', () => {
    const config = normalizeConfig({
      widget_id: 'w',
      primary_color: '#0ea5e9',
      accent_color: 'rgba(14, 165, 233, 0.5)',
      header_color: '#123abc',
      width: '420px',
      height: '70.5rem',
      border_radius: '12px',
      launcher_size: '100%',
      font_family: "Inter, 'Segoe UI', sans-serif-generic",
    });
    expect(config.primary_color).toBe('#0ea5e9');
    expect(config.accent_color).toBe('rgba(14, 165, 233, 0.5)');
    expect(config.header_color).toBe('#123abc');
    expect(config.width).toBe('420px');
    expect(config.height).toBe('70.5rem');
    expect(config.border_radius).toBe('12px');
    expect(config.launcher_size).toBe('100%');
    expect(config.font_family).toBe("Inter, 'Segoe UI', sans-serif-generic");
  });

  it('replaces invalid colors with the theme defaults / null overrides', () => {
    const config = normalizeConfig({
      widget_id: 'w',
      primary_color: 'blue; } body { display: none',
      header_color: 'url(https://evil.example)',
      background_color: 'expression(alert(1))',
    });
    expect(config.primary_color).toBe(DEFAULT_CONFIG.primary_color);
    expect(config.header_color).toBeNull();
    expect(config.background_color).toBeNull();
  });

  it('replaces invalid lengths and font stacks with safe defaults', () => {
    const config = normalizeConfig({
      widget_id: 'w',
      width: 'calc(100vw - 1px)',
      height: '600; position: fixed',
      border_radius: '50vh',
      launcher_size: '-20px',
      font_family: 'url(https://evil.example/x.css)',
    });
    expect(config.width).toBe(DEFAULT_CONFIG.width);
    expect(config.height).toBe(DEFAULT_CONFIG.height);
    expect(config.border_radius).toBe(DEFAULT_CONFIG.border_radius);
    expect(config.launcher_size).toBe(DEFAULT_CONFIG.launcher_size);
    expect(config.font_family).toBeNull();
  });

  it('drops non-http(s) brand image URLs (audit W-22 at the config boundary)', () => {
    const config = normalizeConfig({
      widget_id: 'w',
      logo_url: 'javascript:alert(1)',
      avatar_url: 'data:image/svg+xml;base64,…',
    });
    expect(config.logo_url).toBeNull();
    expect(config.avatar_url).toBeNull();

    const ok = normalizeConfig({
      widget_id: 'w',
      logo_url: 'https://cdn.example.com/logo.png',
    });
    expect(ok.logo_url).toBe('https://cdn.example.com/logo.png');
  });
});
