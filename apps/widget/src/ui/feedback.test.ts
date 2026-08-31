import { describe, expect, it, vi } from 'vitest';
import { createFeedbackControl, type FeedbackRating } from './feedback';

function makeControl() {
  const onSubmit = vi.fn();
  const control = createFeedbackControl({ onSubmit });
  return { control, onSubmit };
}

function click(el: Element): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
}

function clickStar(root: HTMLElement, rating: FeedbackRating): void {
  const star = root.querySelector<HTMLElement>(`.wc-star[data-rating="${rating}"]`);
  if (!star) {
    throw new Error(`No star with data-rating="${rating}"`);
  }
  click(star);
}

function stars(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>('.wc-star'));
}

function pressed(root: HTMLElement): FeedbackRating[] {
  return stars(root)
    .filter((star) => star.getAttribute('aria-pressed') === 'true')
    .map((star) => Number(star.dataset.rating) as FeedbackRating);
}

describe('createFeedbackControl', () => {
  it('renders five stars with aria-pressed="false" and a status region', () => {
    const { control } = makeControl();
    const root = control.element;

    expect(root.className).toContain('wc-feedback');
    const rendered = stars(root);
    expect(rendered).toHaveLength(5);
    expect(rendered.map((star) => star.getAttribute('aria-pressed'))).toEqual(
      Array(5).fill('false'),
    );
    expect(rendered.every((star) => star.tagName === 'BUTTON')).toBe(true);
    // Saved-selection buttons expose their value in a machine-usable way.
    expect(rendered[0].getAttribute('aria-label')).toBe('Rate 1 star');
    expect(rendered[4].getAttribute('aria-label')).toBe('Rate 5 stars');
    // Status region present (role="status") but hidden + empty in the idle state.
    const status = root.querySelector('[role="status"]');
    expect(status).toBeTruthy();
    expect((status as HTMLElement).hidden).toBe(true);
    expect(status?.textContent).toBe('');
    // No comment form / submit button in the compact UX.
    expect(root.querySelector('textarea')).toBeNull();
    expect(root.querySelector('.wc-feedback-submit')).toBeNull();
  });

  it('submits rating 5 immediately on the five-star click', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickStar(root, 5);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({ rating: 5, category: 'helpful', comment: '' });
    expect(pressed(root)).toEqual([1, 2, 3, 4, 5]);
  });

  it('submits rating 1 immediately with the negative category', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickStar(root, 1);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({ rating: 1, category: 'wrong', comment: '' });
    expect(pressed(root)).toEqual([1]);
  });

  it('submits rating 3 as a neutral category', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickStar(root, 3);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({ rating: 3, category: 'other', comment: '' });
    expect(pressed(root)).toEqual([1, 2, 3]);
  });

  it('submits rating 4 as helpful', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickStar(root, 4);

    expect(onSubmit).toHaveBeenCalledWith({ rating: 4, category: 'helpful', comment: '' });
  });

  it('sync(submitted) shows the thanks line and disables all stars', () => {
    const { control } = makeControl();
    const root = control.element;

    clickStar(root, 5);
    control.sync('submitted');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe('Thanks for your feedback');
    expect(stars(root).every((star) => star.hasAttribute('disabled'))).toBe(true);
  });

  it('sync(submitted) after a low rating shows the improvement note', () => {
    const { control } = makeControl();
    const root = control.element;

    clickStar(root, 2);
    control.sync('submitted');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.textContent).toBe("Thanks, we'll improve");
  });

  it('sync(submitting) shows a pending line and disables all stars', () => {
    const { control } = makeControl();
    const root = control.element;
    clickStar(root, 5);

    control.sync('submitting');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe('Sending…');
    expect(stars(root).every((star) => star.hasAttribute('disabled'))).toBe(true);
  });

  it('sync(error) offers a retry prompt and re-enables the stars', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;

    clickStar(root, 4);
    onSubmit.mockClear();

    control.sync('error');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toContain("Couldn't save");
    expect(stars(root).every((star) => !star.hasAttribute('disabled'))).toBe(true);

    // A retry is simply a fresh submit through the same callback.
    clickStar(root, 4);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('sync(idle) hides the status line and restores interactive stars', () => {
    const { control } = makeControl();
    const root = control.element;
    clickStar(root, 5);
    control.sync('submitting');
    control.sync('idle');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(true);
    expect(status.textContent).toBe('');
    expect(stars(root).every((star) => !star.hasAttribute('disabled'))).toBe(true);
  });
});
