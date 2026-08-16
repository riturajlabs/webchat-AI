/**
 * Visitor feedback control (compact UX).
 *
 * A single row of two thumbs — 👍 👎 — under a completed assistant answer.
 * Clicking a thumb immediately submits the rating through the existing
 * feedback API (unchanged) and the control shows a short confirmation line.
 * There is deliberately no modal, no category picker, no comment textarea and
 * no submit button: rating is one tap.
 *
 * The host (mount) owns the network call and drives `sync()` with the
 * feedback status so the control reflects submitting / submitted / error.
 */

import type { FeedbackStatus } from '../stream/chat';

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
  svg.setAttribute('fill', 'currentColor');
  svg.setAttribute('stroke', 'none');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute(
    'd',
    direction === 'up'
      ? 'M1 21h4V9H1v12zM23 10c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z'
      : 'M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z',
  );
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

  const thumbs = document.createElement('div');
  thumbs.className = 'wc-feedback-thumbs';
  thumbs.setAttribute('role', 'group');
  thumbs.setAttribute('aria-label', 'Rate this answer');

  const upButton = button('This answer was helpful', 'wc-thumb wc-thumb-up');
  upButton.setAttribute('aria-pressed', 'false');
  upButton.title = 'This answer was helpful';
  upButton.appendChild(thumbIcon('up'));

  const downButton = button('This answer was not helpful', 'wc-thumb wc-thumb-down');
  downButton.setAttribute('aria-pressed', 'false');
  downButton.title = 'This answer was not helpful';
  downButton.appendChild(thumbIcon('down'));

  thumbs.appendChild(upButton);
  thumbs.appendChild(downButton);

  const note = document.createElement('span');
  note.className = 'wc-feedback-note';
  note.setAttribute('role', 'status');
  note.hidden = true;

  root.appendChild(thumbs);
  root.appendChild(note);

  let selection: 'up' | 'down' | null = null;

  function setPressing(): void {
    upButton.setAttribute('aria-pressed', String(selection === 'up'));
    downButton.setAttribute('aria-pressed', String(selection === 'down'));
  }

  function rate(direction: 'up' | 'down'): void {
    selection = direction;
    setPressing();
    options.onSubmit({
      rating: direction === 'up' ? 5 : 1,
      category: direction === 'up' ? 'helpful' : 'other',
      comment: '',
    });
  }

  upButton.addEventListener('click', () => rate('up'));
  downButton.addEventListener('click', () => rate('down'));

  function sync(status: FeedbackStatus): void {
    if (status === 'submitted') {
      note.textContent =
        selection === 'down' ? "Thanks, we'll improve" : 'Thanks for your feedback';
      note.hidden = false;
      upButton.disabled = true;
      downButton.disabled = true;
    } else if (status === 'error') {
      note.textContent = "Couldn't save. Tap again to retry.";
      note.hidden = false;
      upButton.disabled = false;
      downButton.disabled = false;
    } else if (status === 'submitting') {
      note.textContent = 'Sending…';
      note.hidden = false;
      upButton.disabled = true;
      downButton.disabled = true;
    } else {
      note.textContent = '';
      note.hidden = true;
      upButton.disabled = false;
      downButton.disabled = false;
    }
  }

  return { element: root, sync };
}
