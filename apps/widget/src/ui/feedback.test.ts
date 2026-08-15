import { describe, expect, it, vi } from 'vitest';
import { createFeedbackControl } from './feedback';

function makeControl() {
  const onSubmit = vi.fn();
  const control = createFeedbackControl({ onSubmit });
  return { control, onSubmit };
}

function click(el: Element): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
}

function clickByLabel(root: HTMLElement, label: string): void {
  const target = root.querySelector<HTMLElement>(`[aria-label="${label}"]`);
  if (!target) {
    throw new Error(`No element with aria-label="${label}"`);
  }
  click(target);
}

describe('createFeedbackControl', () => {
  it('renders thumbs with aria-pressed="false" and a status region', () => {
    const { control } = makeControl();
    const root = control.element;

    expect(root.className).toContain('wc-feedback');
    const up = root.querySelector('.wc-thumb-up');
    const down = root.querySelector('.wc-thumb-down');
    expect(up?.getAttribute('aria-pressed')).toBe('false');
    expect(down?.getAttribute('aria-pressed')).toBe('false');
    expect(up?.tagName).toBe('BUTTON');
    expect(down?.tagName).toBe('BUTTON');
    // Status region present (role="status") but hidden + empty in the idle state.
    const status = root.querySelector('[role="status"]');
    expect(status).toBeTruthy();
    expect((status as HTMLElement).hidden).toBe(true);
    expect(status?.textContent).toBe('');
    // No comment form / submit button in the compact UX.
    expect(root.querySelector('textarea')).toBeNull();
    expect(root.querySelector('.wc-feedback-submit')).toBeNull();
  });

  it('submits rating 5 immediately on thumbs-up', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickByLabel(root, 'This answer was helpful');

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({ rating: 5, category: 'helpful', comment: '' });
    expect(root.querySelector('.wc-thumb-up')?.getAttribute('aria-pressed')).toBe('true');
    expect(root.querySelector('.wc-thumb-down')?.getAttribute('aria-pressed')).toBe('false');
  });

  it('submits rating 1 immediately on thumbs-down', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickByLabel(root, 'This answer was not helpful');

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({ rating: 1, category: 'other', comment: '' });
    expect(root.querySelector('.wc-thumb-down')?.getAttribute('aria-pressed')).toBe('true');
  });

  it('sync(submitted) shows the thanks line and disables both thumbs', () => {
    const { control } = makeControl();
    const root = control.element;

    clickByLabel(root, 'This answer was helpful');
    control.sync('submitted');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe('Thanks for your feedback');
    expect(root.querySelector('.wc-thumb-up')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-thumb-down')?.hasAttribute('disabled')).toBe(true);
  });

  it('sync(submitted) after thumbs-down shows the improvement note', () => {
    const { control } = makeControl();
    const root = control.element;

    clickByLabel(root, 'This answer was not helpful');
    control.sync('submitted');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.textContent).toBe("Thanks, we'll improve");
  });

  it('sync(submitting) shows a pending line and disables both thumbs', () => {
    const { control } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was helpful');

    control.sync('submitting');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe('Sending…');
    expect(root.querySelector('.wc-thumb-up')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-thumb-down')?.hasAttribute('disabled')).toBe(true);
  });

  it('sync(error) offers a retry prompt and re-enables the thumbs', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickByLabel(root, 'This answer was helpful');
    onSubmit.mockClear();

    control.sync('error');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toContain("Couldn't save");
    expect(root.querySelector('.wc-thumb-up')?.hasAttribute('disabled')).toBe(false);
    expect(root.querySelector('.wc-thumb-down')?.hasAttribute('disabled')).toBe(false);

    // A retry is simply a fresh submit through the same callback.
    clickByLabel(root, 'This answer was helpful');
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('sync(idle) hides the status line and restores interactive thumbs', () => {
    const { control } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was helpful');
    control.sync('submitting');
    control.sync('idle');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(true);
    expect(status.textContent).toBe('');
    expect(root.querySelector('.wc-thumb-up')?.hasAttribute('disabled')).toBe(false);
  });
});
