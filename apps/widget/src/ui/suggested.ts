/**
 * Suggested-questions row (plan §5).
 *
 * Tap-to-send chips derived from the config. Rendered as real buttons for
 * keyboard + screen-reader accessibility (WCAG 2.2 AA target size ≥ 24×24 px).
 */

export interface SuggestedQuestion {
  label: string;
}

export function createSuggested(
  questions: string[],
  onSelect: (question: string) => void,
): HTMLElement {
  const container = document.createElement('div');
  container.className = 'wc-suggested';

  if (!questions.length) {
    container.hidden = true;
    return container;
  }

  const label = document.createElement('span');
  label.className = 'wc-suggested-label';
  label.textContent = 'Try asking:';
  container.appendChild(label);

  const list = document.createElement('div');
  list.className = 'wc-suggested-list';

  for (const question of questions) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'wc-chip';
    chip.textContent = question;
    chip.addEventListener('click', () => onSelect(question));
    list.appendChild(chip);
  }

  container.appendChild(list);
  return container;
}
