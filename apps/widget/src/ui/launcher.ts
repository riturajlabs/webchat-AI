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
  label.textContent = '💬';
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
