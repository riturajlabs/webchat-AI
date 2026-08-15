/**
 * Floating launcher button (plan §5, WCAG 2.2 AA).
 *
 * A real `<button>` (keyboard + screen-reader operable), positioned via the
 * config-driven CSS custom property `--wc-position`. Toggling it calls the
 * open/close handler. Target size ≥ 24×24 px.
 */

export interface LauncherOptions {
  position: string;
  onToggle: (isOpen: boolean) => void;
  isOpen: () => boolean;
}

export function createLauncher(options: LauncherOptions): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'wc-launcher';
  button.setAttribute('aria-label', 'Chat widget');
  button.setAttribute('aria-expanded', String(options.isOpen()));

  const label = document.createElement('span');
  label.className = 'wc-launcher-icon';
  label.setAttribute('aria-hidden', 'true');
  // Inline SVG chat-bubble: no external asset, safe under a strict CSP.
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '26');
  svg.setAttribute('height', '26');
  svg.setAttribute('fill', 'currentColor');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute(
    'd',
    'M20 2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h14l4 4V4a2 2 0 0 0-2-2zm-8 11H6v-2h6v2zm4-4H6V7h10v2z',
  );
  svg.appendChild(path);
  label.appendChild(svg);
  button.appendChild(label);

  button.addEventListener('click', () => {
    const next = !options.isOpen();
    button.setAttribute('aria-expanded', String(next));
    options.onToggle(next);
  });

  return button;
}

/** Update the launcher's open state (aria + visual). */
export function syncLauncher(button: HTMLButtonElement, isOpen: boolean): void {
  button.setAttribute('aria-expanded', String(isOpen));
  button.classList.toggle('wc-is-open', isOpen);
}
