/**
 * Mobile keyboard handling (audit W-06).
 *
 * iOS keeps `100vh`/fixed layout anchored to the *layout* viewport when the
 * on-screen keyboard opens, so a fixed-position widget ends up underneath the
 * keyboard with the composer occluded. The visual viewport reports the truly
 * visible region; this helper mirrors the occluded height into the
 * `--wc-keyboard-inset` custom property (on `target`) so the widget styles can
 * lift and shrink the window above the keyboard:
 *
 *   inset = max(0, innerHeight - visualViewport.height - visualViewport.offsetTop)
 *
 * Returns a disposer that removes both listeners (`destroy()` wiring).
 */

export interface VisualViewportLike extends EventTarget {
  height: number;
  offsetTop: number;
}

/** CSS custom property receiving the occluded-height inset, e.g. `"320px"`. */
export const KEYBOARD_INSET_VAR = '--wc-keyboard-inset';

export function wireKeyboardInset(
  viewport: VisualViewportLike | null | undefined,
  target: HTMLElement,
  win: { innerHeight: number } = window,
): () => void {
  if (!viewport) {
    return () => {};
  }

  const sync = (): void => {
    const inset = Math.max(0, Math.round(win.innerHeight - viewport.height - viewport.offsetTop));
    target.style.setProperty(KEYBOARD_INSET_VAR, `${inset}px`);
  };

  sync();
  viewport.addEventListener('resize', sync);
  viewport.addEventListener('scroll', sync);
  return () => {
    viewport.removeEventListener('resize', sync);
    viewport.removeEventListener('scroll', sync);
  };
}
