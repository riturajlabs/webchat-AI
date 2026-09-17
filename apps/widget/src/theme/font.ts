/**
 * Curated web font registry and on-demand stylesheet loader.
 *
 * Prevents bundling heavy font binaries into the widget package while ensuring
 * that selected typography actually renders distinctly across platforms.
 *
 * Security: Only fonts explicitly present in `CURATED_FONTS` trigger external
 * font loading. Arbitrary strings or external URLs are never injected.
 */

export interface CuratedFont {
  key: string;
  label: string;
  stack: string;
  stylesheetUrl: string | null;
}

export const CURATED_FONTS: readonly CuratedFont[] = [
  {
    key: 'system',
    label: 'System default',
    stack: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
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
    key: 'roboto',
    label: 'Roboto',
    stack: "'Roboto', system-ui, -apple-system, sans-serif",
    stylesheetUrl: 'https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap',
  },
  {
    key: 'open-sans',
    label: 'Open Sans',
    stack: "'Open Sans', system-ui, -apple-system, sans-serif",
    stylesheetUrl:
      'https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;500;600;700&display=swap',
  },
  {
    key: 'montserrat',
    label: 'Montserrat',
    stack: "'Montserrat', system-ui, -apple-system, sans-serif",
    stylesheetUrl:
      'https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap',
  },
  {
    key: 'lato',
    label: 'Lato',
    stack: "'Lato', system-ui, -apple-system, sans-serif",
    stylesheetUrl: 'https://fonts.googleapis.com/css2?family=Lato:wght@400;700&display=swap',
  },
  {
    key: 'playfair-display',
    label: 'Playfair Display',
    stack: "'Playfair Display', Georgia, serif",
    stylesheetUrl:
      'https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700&display=swap',
  },
  {
    key: 'space-grotesk',
    label: 'Space Grotesk',
    stack: "'Space Grotesk', system-ui, -apple-system, sans-serif",
    stylesheetUrl:
      'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&display=swap',
  },
];

/**
 * Match a configured font-family string against the curated registry.
 * Matches by exact stack, key, or primary family name.
 */
export function matchCuratedFont(fontFamily: string | null | undefined): CuratedFont | null {
  if (!fontFamily || typeof fontFamily !== 'string') {
    return null;
  }
  const clean = fontFamily.trim().toLowerCase();

  // 1. Explicit system font checks
  const systemFont = CURATED_FONTS.find((c) => c.key === 'system');
  if (
    clean === 'system' ||
    clean === 'system default' ||
    (systemFont && clean === systemFont.stack.toLowerCase())
  ) {
    return null;
  }

  // 2. Exact stack match
  for (const candidate of CURATED_FONTS) {
    if (candidate.key === 'system') continue;
    if (candidate.stack.toLowerCase() === clean) {
      return candidate;
    }
  }

  // 3. Exact key match
  for (const candidate of CURATED_FONTS) {
    if (candidate.key === 'system') continue;
    if (candidate.key === clean) {
      return candidate;
    }
  }

  // 4. Primary family name match
  for (const candidate of CURATED_FONTS) {
    if (candidate.key === 'system') continue;
    const labelLower = candidate.label.toLowerCase();
    if (
      clean === labelLower ||
      clean.startsWith(`'${labelLower}'`) ||
      clean.startsWith(`"${labelLower}"`) ||
      clean.startsWith(`${labelLower},`) ||
      clean.startsWith(`${labelLower} `)
    ) {
      return candidate;
    }
  }

  return null;
}

/**
 * Inject the approved stylesheet link for a curated web font into the document head.
 * Safe against duplicate insertions, offline mode, and restrictive CSPs.
 */
export function loadWebFont(fontFamily: string | null | undefined, doc?: Document): void {
  const targetDoc = doc ?? (typeof document !== 'undefined' ? document : undefined);
  if (!targetDoc || !targetDoc.head) {
    return;
  }

  const font = matchCuratedFont(fontFamily);
  if (!font || !font.stylesheetUrl) {
    return;
  }

  const selector = `link[data-webchat-font="${font.key}"]`;
  if (targetDoc.querySelector(selector)) {
    return;
  }

  try {
    const link = targetDoc.createElement('link');
    link.rel = 'stylesheet';
    link.href = font.stylesheetUrl;
    link.setAttribute('data-webchat-font', font.key);
    targetDoc.head.appendChild(link);
  } catch {
    // Gracefully ignore DOM/CSP errors; system fallback font takes over
  }
}
