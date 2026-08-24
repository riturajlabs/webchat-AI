import { describe, expect, it } from 'vitest';
import { wireKeyboardInset, KEYBOARD_INSET_VAR, type VisualViewportLike } from './viewport';

/**
 * Minimal stand-in for window.visualViewport: a real EventTarget carrying
 * mutable geometry, so tests dispatch 'resize'/'scroll' events natively.
 */
function fakeViewport(height: number, offsetTop = 0): VisualViewportLike {
  return Object.assign(new EventTarget(), { height, offsetTop }) as VisualViewportLike;
}

function fire(viewport: VisualViewportLike, type: string): void {
  viewport.dispatchEvent(new Event(type));
}

describe('wireKeyboardInset (audit W-06)', () => {
  it('mirrors the keyboard-occluded height into --wc-keyboard-inset', () => {
    const target = document.createElement('div');
    // 800px window, 300px visible viewport -> keyboard covers 500px.
    const vp = fakeViewport(300);
    const dispose = wireKeyboardInset(vp, target, { innerHeight: 800 });

    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('500px');

    // Keyboard closes: the inset must return to zero.
    vp.height = 800;
    fire(vp, 'resize');
    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('0px');
    dispose();
  });

  it('subtracts the visual viewport scroll offset', () => {
    const target = document.createElement('div');
    const vp = fakeViewport(400, 50);
    const dispose = wireKeyboardInset(vp, target, { innerHeight: 800 });
    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('350px');

    vp.offsetTop = 120;
    fire(vp, 'scroll'); // page scrolled while the keyboard is open
    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('280px');
    dispose();
  });

  it('clamps to zero when the visible viewport is taller than innerHeight', () => {
    const target = document.createElement('div');
    const dispose = wireKeyboardInset(fakeViewport(900), target, { innerHeight: 800 });
    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('0px');
    dispose();
  });

  it('is a no-op without a visual viewport (desktop / old browsers)', () => {
    const target = document.createElement('div');
    const dispose = wireKeyboardInset(null, target, { innerHeight: 800 });
    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('');
    expect(() => dispose()).not.toThrow();
  });

  it('disposer removes both listeners so later events change nothing', () => {
    const target = document.createElement('div');
    const vp = fakeViewport(300);
    const dispose = wireKeyboardInset(vp, target, { innerHeight: 800 });
    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('500px');

    dispose();
    vp.height = 100;
    fire(vp, 'resize');
    fire(vp, 'scroll');
    expect(target.style.getPropertyValue(KEYBOARD_INSET_VAR)).toBe('500px');
  });
});
