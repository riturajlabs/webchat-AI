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
    // Prompt visible until selection.
    expect(root.querySelector('.wc-feedback-prompt')?.textContent).toBe('Was this helpful?');
    // Status region present (role="status") but empty in the idle state.
    const status = root.querySelector('[role="status"]');
    expect(status?.textContent).toBe('');
  });

  it('reveals the panel on thumbs-up and offers only "helpful" + "other" chips', () => {
    const { control } = makeControl();
    const root = control.element;

    clickByLabel(root, 'This answer was helpful');

    expect(root.querySelector('.wc-thumb-up')?.getAttribute('aria-pressed')).toBe('true');
    const panel = root.querySelector('.wc-feedback-panel') as HTMLElement;
    expect(panel.hidden).toBe(false);
    const chips = Array.from(root.querySelectorAll('.wc-feedback-chip'));
    expect(chips.map((c) => c.textContent).sort()).toEqual(['helpful', 'other']);
    // Default category for thumbs-up is "helpful".
    const pressed = chips.filter((c) => c.getAttribute('aria-pressed') === 'true');
    expect(pressed.map((c) => c.textContent)).toEqual(['helpful']);
  });

  it('reveals the panel on thumbs-down with the wider category set', () => {
    const { control } = makeControl();
    const root = control.element;

    clickByLabel(root, 'This answer was not helpful');

    expect(root.querySelector('.wc-thumb-down')?.getAttribute('aria-pressed')).toBe('true');
    const chips = Array.from(root.querySelectorAll('.wc-feedback-chip'));
    expect(chips.map((c) => c.textContent).sort()).toEqual([
      'incomplete',
      'offensive',
      'other',
      'wrong',
    ]);
  });

  it('selects a category chip and keeps aria-pressed in sync', () => {
    const { control } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was not helpful');

    // Click "wrong"; `renderChips()` re-creates the chip nodes after each
    // selection, so re-query for the chip after the click.
    const wrongBefore = Array.from(root.querySelectorAll('.wc-feedback-chip')).find(
      (chip) => chip.textContent === 'wrong',
    );
    click(wrongBefore!);

    const wrongAfter = Array.from(root.querySelectorAll('.wc-feedback-chip')).find(
      (chip) => chip.textContent === 'wrong',
    );
    expect(wrongAfter?.getAttribute('aria-pressed')).toBe('true');
    const others = Array.from(root.querySelectorAll('.wc-feedback-chip')).filter(
      (chip) => chip !== wrongAfter,
    );
    for (const chip of others) {
      expect(chip.getAttribute('aria-pressed')).toBe('false');
    }
  });

  it('submits the trimmed comment with the selected rating + category', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was helpful');
    const textarea = root.querySelector<HTMLTextAreaElement>('.wc-feedback-comment');
    expect(textarea).toBeTruthy();
    textarea!.value = '   very helpful!   ';
    textarea!.dispatchEvent(new Event('input', { bubbles: true }));
    clickByLabel(root, 'Submit feedback');

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      rating: 5,
      category: 'helpful',
      comment: 'very helpful!',
    });
  });

  it('submits rating 1 + the chosen category for thumbs-down', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was not helpful');
    const incomplete = Array.from(root.querySelectorAll('.wc-feedback-chip')).find(
      (chip) => chip.textContent === 'incomplete',
    );
    click(incomplete!);
    clickByLabel(root, 'Submit feedback');

    expect(onSubmit).toHaveBeenCalledWith({
      rating: 1,
      category: 'incomplete',
      comment: '',
    });
  });

  it('cancels the panel and clears the selection', () => {
    const { control } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was helpful');

    const panel = root.querySelector('.wc-feedback-panel') as HTMLElement;
    expect(panel.hidden).toBe(false);
    clickByLabel(root, 'Cancel feedback');

    expect(panel.hidden).toBe(true);
    expect(root.querySelector('.wc-thumb-up')?.getAttribute('aria-pressed')).toBe('false');
    expect(root.querySelector('.wc-thumb-down')?.getAttribute('aria-pressed')).toBe('false');
  });

  it('sync(submitted) hides the body, shows the thanks message, and disables controls', () => {
    const { control } = makeControl();
    const root = control.element;

    const body = root.querySelector('.wc-feedback-body') as HTMLElement;
    const thanks = root.querySelector('.wc-feedback-thanks') as HTMLElement;
    // `thanks` starts visible (no `.hidden = true` is set in the factory);
    // sync() is what toggles it.
    expect(thanks.textContent).toBe('Thanks for your feedback!');

    control.sync('submitted');

    expect(body.hidden).toBe(true);
    expect(thanks.hidden).toBe(false);
    expect(thanks.textContent).toBe('Thanks for your feedback!');
    expect(root.querySelector('.wc-thumb-up')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-thumb-down')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-feedback-submit')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-feedback-cancel')?.hasAttribute('disabled')).toBe(true);
  });

  it('sync(submitting) shows the "Submitting…" status and disables all controls', () => {
    const { control } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was helpful');

    control.sync('submitting');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe('Submitting…');
    expect(root.querySelector('.wc-thumb-up')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-thumb-down')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-feedback-submit')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-feedback-chip')?.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('.wc-feedback-comment')?.hasAttribute('disabled')).toBe(true);
  });

  it('sync(error) shows the error surface with Retry + Dismiss that re-invoke onSubmit / hide', () => {
    const { control, onSubmit } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was helpful');
    clickByLabel(root, 'Submit feedback');
    onSubmit.mockClear();

    control.sync('error');

    const err = root.querySelector('.wc-feedback-error') as HTMLElement;
    expect(err.hidden).toBe(false);
    expect(err.getAttribute('role')).toBe('alert');
    expect(err.textContent).toContain("Couldn't send feedback.");

    clickByLabel(root, 'Retry sending feedback');
    expect(onSubmit).toHaveBeenCalledTimes(1);

    clickByLabel(root, 'Dismiss feedback error');
    expect(err.hidden).toBe(true);
  });

  it('sync(idle) hides submitting status and restores an interactive body', () => {
    const { control } = makeControl();
    const root = control.element;
    clickByLabel(root, 'This answer was helpful');
    control.sync('submitting');
    control.sync('idle');

    const status = root.querySelector('[role="status"]') as HTMLElement;
    expect(status.hidden).toBe(true);
    expect(status.textContent).toBe('');
    expect(root.querySelector('.wc-thumb-up')?.hasAttribute('disabled')).toBe(false);
    const body = root.querySelector('.wc-feedback-body') as HTMLElement;
    expect(body.hidden).toBe(false);
  });
});
