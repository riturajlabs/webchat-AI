# WebChat AI — Themes

Shared widget theme presets + resolve engine, consumed by both the
[widget SDK](../../apps/widget) (runtime styles) and the
[dashboard](../../apps/dashboard) (preview + editor) so a configured theme
renders identically everywhere.

- **Package:** `@webchat/themes` (workspace, `src/index.ts`)
- **Dependencies:** none at runtime — pure TypeScript helpers
- **Version:** 0.1.0

## What it provides

A theme is either a **preset** (curated light/dark palette) or the classic
fully-custom setup. `resolveTheme(config, dark)` merges the two into a single
`ResolvedTheme` of fully-specified color/gradient tokens ready to apply as CSS
custom properties on the widget host.

- `THEME_PRESETS` — 10 curated presets, each with `light` and `dark` token sets:
  `ocean-blue`, `midnight-dark`, `emerald-support`, `purple-ai`, `minimal-white`,
  `sunset`, `modern-gradient` (gradient header), `whatsapp-classic`,
  `ios-native`, `enterprise-slate`.
- `getThemePreset(id)` / `THEME_PRESET_IDS` — lookup helpers.
- `resolveTheme(config, dark)` — the resolution rules below.
- `readableText(hex)` / `relativeLuminance(hex)` — WCAG-style on-color text and
  luminance helpers used by the resolver.

## Resolution rules (`resolveTheme`)

`ThemeConfig` is a subset of the widget config: `theme_preset`, `primary_color`,
`accent_color`, `secondary_color`, `header_color`, `background_color`,
`text_color`.

1. A preset's `light`/`dark` palette is the base (or the classic default tokens
   when `theme_preset` is unset/unknown).
2. Explicit `primary_color` / `accent_color` overrides win — except when the
   value equals the platform default (`#10A37F` / `#25D366`), which counts as
   "not overridden" so selecting a preset actually changes the palette.
3. Direct overrides `header_color`, `background_color`, `text_color` always win.
4. Semantic tokens (send button, launcher, focus ring, online indicator, …) are
   derived centrally — presets may override them; otherwise documented fallbacks
   (e.g. primary→secondary gradient send button) apply. This keeps renderers
   consuming intent-named tokens instead of inventing color logic.

## Persistence

The dashboard persists `theme_preset` (or the direct overrides) through the
widget config API. `theme_preset` is a bounded string (`max_length=32`) on the
backend schema; the widget resolves the preset client-side at render time, so a
new preset ships without a backend change. The backend does not duplicate the
preset data.

## Testing

```bash
pnpm --filter @webchat/themes test   # vitest run (src/index.test.ts)
```

Tests cover preset token completeness, resolution precedence, dark/light
selection, and readable-text contrast decisions.
