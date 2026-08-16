/**
 * Inline SVG glyphs shared across widget UI components.
 *
 * Everything is stroke/fill `currentColor` and `aria-hidden`, so these are
 * purely decorative and inherit the surrounding text color. No external
 * assets or icon fonts are referenced (self-containment audit).
 */

function svg(viewBox: string, width: number, height: number): SVGSVGElement {
  const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  node.setAttribute('viewBox', viewBox);
  node.setAttribute('width', String(width));
  node.setAttribute('height', String(height));
  node.setAttribute('fill', 'none');
  node.setAttribute('stroke', 'currentColor');
  node.setAttribute('stroke-width', '1.8');
  node.setAttribute('stroke-linecap', 'round');
  node.setAttribute('stroke-linejoin', 'round');
  node.setAttribute('aria-hidden', 'true');
  node.setAttribute('focusable', 'false');
  return node;
}

function path(d: string): SVGPathElement {
  const node = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  node.setAttribute('d', d);
  return node;
}

/** Default brand avatar: a minimal chat-bot glyph. */
export function botGlyph(): SVGSVGElement {
  const node = svg('0 0 24 24', 20, 20);
  node.appendChild(path('M4 8h16v11H4z'));
  node.appendChild(path('M12 8V5'));
  node.appendChild(path('M9 15.5h6'));
  const leftEye = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  leftEye.setAttribute('cx', '9');
  leftEye.setAttribute('cy', '12.5');
  leftEye.setAttribute('r', '0.5');
  leftEye.setAttribute('fill', 'currentColor');
  leftEye.setAttribute('stroke', 'none');
  const rightEye = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  rightEye.setAttribute('cx', '15');
  rightEye.setAttribute('cy', '12.5');
  rightEye.setAttribute('r', '0.5');
  rightEye.setAttribute('fill', 'currentColor');
  rightEye.setAttribute('stroke', 'none');
  node.appendChild(leftEye);
  node.appendChild(rightEye);
  return node;
}

/** Small brand spark for the "Powered by WebChat AI" footer. */
export function footerLogo(): SVGSVGElement {
  const node = svg('0 0 24 24', 12, 12);
  node.setAttribute('fill', 'currentColor');
  node.setAttribute('stroke', 'none');
  node.appendChild(
    path(
      'M12 2l1.8 5.4 5.7-.9-3.8 4.4 3.8 4.4-5.7-.9L12 20l-1.8-5.4-5.7.9 3.8-4.4-3.8-4.4 5.7.9L12 2z',
    ),
  );
  return node;
}

/** External-link glyph shown inside source cards. */
export function externalLinkGlyph(): SVGSVGElement {
  const node = svg('0 0 24 24', 12, 12);
  node.setAttribute('stroke-width', '2');
  node.appendChild(path('M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'));
  node.appendChild(path('M15 3h6v6'));
  node.appendChild(path('M10 14 21 3'));
  return node;
}

/** Document glyph used as a favicon fallback inside source cards. */
export function documentGlyph(): SVGSVGElement {
  const node = svg('0 0 24 24', 14, 14);
  node.setAttribute('stroke-width', '1.6');
  node.appendChild(path('M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z'));
  node.appendChild(path('M14 3v5h5'));
  node.appendChild(path('M9 13h6'));
  node.appendChild(path('M9 17h6'));
  return node;
}

/** Close (X) glyph for the chat window header. */
export function closeIcon(): SVGSVGElement {
  const node = svg('0 0 24 24', 18, 18);
  node.setAttribute('stroke-width', '2');
  node.appendChild(path('M18 6 6 18'));
  node.appendChild(path('M6 6l12 12'));
  return node;
}
