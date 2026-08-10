import { describe, expect, it, vi } from 'vitest';
import { createSuggested } from './suggested';

describe('createSuggested', () => {
  it('is hidden when there are no questions', () => {
    const element = createSuggested([], vi.fn());
    expect(element.hidden).toBe(true);
  });

  it('renders a labelled row of real buttons', () => {
    const onSelect = vi.fn();
    const element = createSuggested(['What is pricing?', 'How do I integrate?'], onSelect);
    expect(element.hidden).toBe(false);
    expect(element.querySelector('.wc-suggested-label')?.textContent).toBe('Try asking:');
    const chips = element.querySelectorAll('button.wc-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toBe('What is pricing?');
  });

  it('fires onSelect with the question text', () => {
    const onSelect = vi.fn();
    const element = createSuggested(['Hello?'], onSelect);
    (element.querySelector('.wc-chip') as HTMLButtonElement).click();
    expect(onSelect).toHaveBeenCalledWith('Hello?');
  });
});
