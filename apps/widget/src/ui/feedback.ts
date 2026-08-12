/**
 * Visitor feedback control (Phase 12.4, ADR-005 §5.6, WCAG 2.2 AA).
 *
 * A compact, keyboard-accessible control rendered under a completed assistant
 * answer. Flow: thumbs up / thumbs down → optional category + comment →
 * Submit. The control owns its internal selection (thumb, category, comment);
 * the host (mount) owns the network call and drives `sync()` with the
 * feedback status so the control reflects submitting / submitted / error
 * without losing the visitor's input. All interactive elements are native
 * buttons / textarea with labels and `aria-pressed` state.
 */

import type { FeedbackStatus } from '../stream/chat';

/** Widget feedback categories the backend accepts (ADR-005 §5.6). */
const UP_CATEGORIES = ['helpful', 'other'];
const DOWN_CATEGORIES = ['wrong', 'incomplete', 'offensive', 'other'];

export interface FeedbackSubmitPayload {
  /** 1-5 scale: thumbs up → 5, thumbs down → 1. */
  rating: 1 | 5;
  category: string;
  comment: string;
}

export interface FeedbackControl {
  element: HTMLElement;
  /** Reflect a feedback status change (submitting / submitted / error / idle). */
  sync(status: FeedbackStatus): void;
}

export interface FeedbackControlOptions {
  onSubmit: (payload: FeedbackSubmitPayload) => void;
}

function thumbIcon(direction: 'up' | 'down'): SVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute(
    'd',
    direction === 'up'
      ? 'M2 21h15v-2l.5-4.5H21a2 2 0 0 0 2-2v-1.5a2 2 0 0 0-.2-.9L19.5 5.7A3 3 0 0 0 16.8 4H8.8a3 3 0 0 0-2.6 1.5L3 11v1.5L1.2 15V19a2 2 0 0 0 .8 2z' +
          ' M1 19a2 2 0 0 0 2 2h2v-8H3a2 2 0 0 0-2 2v4z'
      : 'M22 3H7v2l.5 4.5H3a2 2 0 0 0-2 2v1.5a2 2 0 0 0 .2.9L4.5 18.3a3 3 0 0 0 2.7 1.7h8a3 3 0 0 0 2.6-1.5L21 13v-1.5L22.8 9V5a2 2 0 0 0-.8-2z' +
          ' M23 5a2 2 0 0 0-2-2h-2v8h2a2 2 0 0 0 2-2V5z',
  );
  path.setAttribute('fill', 'currentColor');
  svg.appendChild(path);
  return svg;
}

function button(label: string, className: string): HTMLButtonElement {
  const node = document.createElement('button');
  node.type = 'button';
  node.className = className;
  node.setAttribute('aria-label', label);
  return node;
}

export function createFeedbackControl(options: FeedbackControlOptions): FeedbackControl {
  const root = document.createElement('div');
  root.className = 'wc-feedback';

  // --- Body: prompt + thumbs + category/comment panel ---------------------
  const body = document.createElement('div');
  body.className = 'wc-feedback-body';

  const prompt = document.createElement('span');
  prompt.className = 'wc-feedback-prompt';
  prompt.textContent = 'Was this helpful?';
  body.appendChild(prompt);

  const thumbs = document.createElement('div');
  thumbs.className = 'wc-feedback-thumbs';
  thumbs.setAttribute('role', 'group');
  thumbs.setAttribute('aria-label', 'Rate this answer');

  const upButton = button('This answer was helpful', 'wc-thumb wc-thumb-up');
  upButton.setAttribute('aria-pressed', 'false');
  upButton.appendChild(thumbIcon('up'));

  const downButton = button('This answer was not helpful', 'wc-thumb wc-thumb-down');
  downButton.setAttribute('aria-pressed', 'false');
  downButton.appendChild(thumbIcon('down'));

  thumbs.appendChild(upButton);
  thumbs.appendChild(downButton);
  body.appendChild(thumbs);

  // Category + comment panel (revealed once a thumb is selected).
  const panel = document.createElement('div');
  panel.className = 'wc-feedback-panel';
  panel.hidden = true;

  const panelLabel = document.createElement('span');
  panelLabel.className = 'wc-feedback-panel-label';
  body.appendChild(panelLabel);

  const categories = document.createElement('div');
  categories.className = 'wc-feedback-categories';
  categories.setAttribute('role', 'radiogroup');
  categories.setAttribute('aria-label', 'Choose a category');

  const commentWrap = document.createElement('div');
  commentWrap.className = 'wc-feedback-comment-wrap';

  const commentLabel = document.createElement('label');
  commentLabel.className = 'wc-feedback-comment-label';
  commentLabel.textContent = 'Add a comment (optional)';
  commentLabel.htmlFor = 'wc-feedback-comment';
  commentWrap.appendChild(commentLabel);

  const comment = document.createElement('textarea');
  comment.id = 'wc-feedback-comment';
  comment.className = 'wc-feedback-comment';
  comment.rows = 2;
  comment.placeholder = 'Share more detail…';
  commentWrap.appendChild(comment);

  const actions = document.createElement('div');
  actions.className = 'wc-feedback-actions';

  const submit = button('Submit feedback', 'wc-feedback-submit');
  submit.textContent = 'Submit';
  const cancel = button('Cancel feedback', 'wc-feedback-cancel');
  cancel.textContent = 'Cancel';
  actions.appendChild(submit);
  actions.appendChild(cancel);

  panel.appendChild(categories);
  panel.appendChild(commentWrap);
  panel.appendChild(actions);

  body.appendChild(panel);
  body.insertBefore(panelLabel, panel);

  // --- Status / success / error surfaces ---------------------------------
  const status = document.createElement('div');
  status.className = 'wc-feedback-status';
  status.setAttribute('role', 'status');

  const error = document.createElement('div');
  error.className = 'wc-feedback-error';
  error.setAttribute('role', 'alert');
  error.hidden = true;
  const errorText = document.createElement('span');
  errorText.className = 'wc-feedback-error-text';
  errorText.textContent = "Couldn't send feedback.";
  const retry = button('Retry sending feedback', 'wc-feedback-retry');
  retry.textContent = 'Retry';
  const dismiss = button('Dismiss feedback error', 'wc-feedback-dismiss');
  dismiss.textContent = 'Dismiss';
  error.appendChild(errorText);
  error.appendChild(retry);
  error.appendChild(dismiss);

  const thanks = document.createElement('div');
  thanks.className = 'wc-feedback-thanks';
  thanks.textContent = 'Thanks for your feedback!';

  root.appendChild(body);
  root.appendChild(status);
  root.appendChild(error);
  root.appendChild(thanks);

  // --- Internal selection state -------------------------------------------
  let selection: 'up' | 'down' | null = null;
  let category: string | null = null;
  let commentValue = '';
  let lastPayload: FeedbackSubmitPayload | null = null;
  let chipButtons: HTMLButtonElement[] = [];

  function rating(): 1 | 5 {
    return selection === 'down' ? 1 : 5;
  }

  function defaultCategory(): string {
    return selection === 'down' ? 'other' : 'helpful';
  }

  function renderChips(): void {
    chipButtons.forEach((chip) => chip.remove());
    chipButtons = [];
    const items = selection === 'down' ? DOWN_CATEGORIES : UP_CATEGORIES;
    for (const value of items) {
      const chip = button(`Category ${value}`, 'wc-feedback-chip');
      chip.textContent = value;
      chip.setAttribute('aria-pressed', String(category === value));
      chip.addEventListener('click', () => {
        category = value;
        renderChips();
      });
      categories.appendChild(chip);
      chipButtons.push(chip);
    }
  }

  function showPanel(): void {
    category = defaultCategory();
    commentValue = comment.value;
    panelLabel.textContent = selection === 'down' ? 'What went wrong?' : 'What did you think?';
    renderChips();
    panel.hidden = false;
    comment.focus();
  }

  function hidePanel(): void {
    panel.hidden = true;
    category = null;
  }

  function setPressing(): void {
    upButton.setAttribute('aria-pressed', String(selection === 'up'));
    downButton.setAttribute('aria-pressed', String(selection === 'down'));
  }

  function sync(statusValue: FeedbackStatus): void {
    status.textContent = statusValue === 'submitting' ? 'Submitting…' : '';
    status.hidden = statusValue !== 'submitting';
    const interactiveDisabled = statusValue === 'submitting' || statusValue === 'submitted';
    upButton.disabled = interactiveDisabled;
    downButton.disabled = interactiveDisabled;
    submit.disabled = interactiveDisabled;
    cancel.disabled = statusValue === 'submitting' || statusValue === 'submitted';
    comment.disabled = statusValue === 'submitting' || statusValue === 'submitted';
    chipButtons.forEach((chip) => {
      chip.disabled = statusValue === 'submitting' || statusValue === 'submitted';
    });
    body.hidden = statusValue === 'submitted';
    thanks.hidden = statusValue !== 'submitted';
    error.hidden = statusValue !== 'error';
    if (statusValue !== 'error') {
      lastPayload = null;
    }
  }

  function send(): void {
    const payload: FeedbackSubmitPayload = {
      rating: rating(),
      category: category ?? defaultCategory(),
      comment: commentValue.trim(),
    };
    lastPayload = payload;
    options.onSubmit(payload);
  }

  upButton.addEventListener('click', () => {
    selection = 'up';
    setPressing();
    showPanel();
  });

  downButton.addEventListener('click', () => {
    selection = 'down';
    setPressing();
    showPanel();
  });

  comment.addEventListener('input', () => {
    commentValue = comment.value;
  });

  submit.addEventListener('click', () => {
    commentValue = comment.value;
    send();
  });

  cancel.addEventListener('click', () => {
    hidePanel();
    selection = null;
    setPressing();
  });

  retry.addEventListener('click', () => {
    if (lastPayload) {
      options.onSubmit(lastPayload);
    }
  });

  dismiss.addEventListener('click', () => {
    error.hidden = true;
  });

  return { element: root, sync };
}
