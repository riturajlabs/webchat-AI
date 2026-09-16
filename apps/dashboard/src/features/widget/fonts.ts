/**
 * Curated typography options and on-demand web font loader for dashboard widget preview.
 *
 * Provides a vetted list of visually distinctive typefaces. When an option is selected,
 * its stylesheet is dynamically injected into the dashboard document head so the admin
 * immediately sees true typography in the preview.
 */

export interface CuratedFontOption {
  key: string;
  label: string;
  stack: string | null;
  stylesheetUrl: string | null;
}

export const CURATED_FONTS: readonly CuratedFontOption[] = [
  {
    key: 'system',
    label: 'System default',
    stack: null,
    stylesheetUrl: null,
  },
  {
    key: 'inter',
    label: 'Inter',
    stack: "'Inter', system-ui, -apple-system, sans-serif",
    stylesheetUrl: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap',
  },
  {
    key: 'poppins',
    label: 'Poppins',
    stack: "'Poppins', system-ui, -apple-system, sans-serif",
    stylesheetUrl: 'https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap',
  },
  {
    key: 'nunito',
    label: 'Nunito',
    stack: "'Nunito', system-ui, -apple-system, sans-serif",
    stylesheetUrl: 'https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap',
  },
  {
    key: 'playfair-display',
    label: 'Playfair Display',
    stack: "'Playfair Display', Georgia, serif",
    stylesheetUrl:
      'https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;600;700&display=swap',
  },
  {
    key: 'space-grotesk',
    label: 'Space Grotesk',
    stack: "'Space Grotesk', system-ui, -apple-system, sans-serif",
    stylesheetUrl:
      'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&display=swap',
  },
];

export const FONT_OPTIONS = CURATED_FONTS;

export function fontFamilyToKey(value: string | null | undefined): string {
  if (!value) return 'system';
  const clean = value.toLowerCase();
  const match = CURATED_FONTS.find(
    (option) =>
      option.key !== 'system' &&
      (option.stack?.toLowerCase() === clean ||
        clean.includes(option.key) ||
        clean.includes(option.label.toLowerCase())),
  );
  return match ? match.key : 'system';
}

export function fontKeyToStack(key: string): string | null {
  const option = CURATED_FONTS.find((candidate) => candidate.key === key);
  return option ? option.stack : null;
}

/**
 * On-demand stylesheet loader for the dashboard widget preview.
 * Deduplicates stylesheet injection to avoid unbounded link accumulation.
 */
export function loadPreviewFont(fontFamily: string | null | undefined): void {
  if (typeof document === 'undefined') return;
  const key = fontFamilyToKey(fontFamily);
  if (key === 'system') return;
  const font = CURATED_FONTS.find((f) => f.key === key);
  if (!font?.stylesheetUrl) return;

  const selector = `link[data-webchat-preview-font="${font.key}"]`;
  if (document.querySelector(selector)) return;

  try {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = font.stylesheetUrl;
    link.setAttribute('data-webchat-preview-font', font.key);
    document.head.appendChild(link);
  } catch {
    // Graceful fallback to system typography
  }
}
