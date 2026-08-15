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
