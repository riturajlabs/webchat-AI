/**
 * Visitor feedback control — 1 to 5 star rating.
 *
 * A single row of five stars under a completed assistant answer. Clicking a
 * star immediately submits that rating through the existing feedback API
 * (unchanged) and the control shows a short confirmation line. There is
 * deliberately no modal, no category picker, no comment textarea and no submit
 * button: rating is one tap.
 *
 * The host (mount) owns the network call and drives `sync()` with the
 * feedback status so the control reflects submitting / submitted / error.
 */

import type { FeedbackStatus } from '../stream/chat';

/** Star ratings on the backend 1-5 scale. */
export type FeedbackRating = 1 | 2 | 3 | 4 | 5;

export interface FeedbackSubmitPayload {
  /** 1-5 scale; 4-5 map to `helpful`, 3 to `other`, 1-2 to `wrong`. */
  rating: FeedbackRating;
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

function starIcon(): SVGElement {
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
    'M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z',
  );
  svg.appendChild(path);
  return svg;
}

function starButton(rating: FeedbackRating): HTMLButtonElement {
  const node = document.createElement('button');
  node.type = 'button';
  node.className = 'wc-star';
  node.dataset.rating = String(rating);
  const label = labelForRating(rating);
  node.setAttribute('aria-label', label);
  node.title = label;
  node.setAttribute('aria-pressed', 'false');
  node.appendChild(starIcon());
  return node;
}

function labelForRating(rating: FeedbackRating): string {
  return `Rate ${rating} star${rating === 1 ? '' : 's'}`;
}

/** Backend category derived from the star rating (ADR-005 §5.6 taxonomy). */
export function categoryForRating(rating: FeedbackRating): string {
  if (rating >= 4) {
    return 'helpful';
  }
  if (rating === 3) {
    return 'other';
  }
  return 'wrong';
}

export function createFeedbackControl(options: FeedbackControlOptions): FeedbackControl {
  const root = document.createElement('div');
  root.className = 'wc-feedback';

  const stars = document.createElement('div');
  stars.className = 'wc-feedback-stars';
  stars.setAttribute('role', 'group');
  stars.setAttribute('aria-label', 'Rate this answer (1 to 5 stars)');

  const buttons = [1, 2, 3, 4, 5].map((rating) => starButton(rating as FeedbackRating));
  for (const button of buttons) {
    stars.appendChild(button);
  }

  const note = document.createElement('span');
  note.className = 'wc-feedback-note';
  note.setAttribute('role', 'status');
  note.hidden = true;

  root.appendChild(stars);
  root.appendChild(note);

  let selection: FeedbackRating | null = null;

  function setPressing(): void {
    for (const button of buttons) {
      const rating = Number(button.dataset.rating) as FeedbackRating;
      button.setAttribute('aria-pressed', String(selection !== null && rating <= selection));
    }
  }

  function rate(rating: FeedbackRating): void {
    selection = rating;
    setPressing();
    options.onSubmit({
      rating,
      category: categoryForRating(rating),
      comment: '',
    });
  }

  for (const button of buttons) {
    button.addEventListener('click', () => rate(Number(button.dataset.rating) as FeedbackRating));
  }

  function sync(status: FeedbackStatus): void {
    if (status === 'submitted') {
      note.textContent =
        selection !== null && selection <= 3 ? "Thanks, we'll improve" : 'Thanks for your feedback';
      note.hidden = false;
      for (const button of buttons) {
        button.disabled = true;
      }
    } else if (status === 'error') {
      note.textContent = "Couldn't save. Tap again to retry.";
      note.hidden = false;
      for (const button of buttons) {
        button.disabled = false;
      }
    } else if (status === 'submitting') {
      note.textContent = 'Sending…';
      note.hidden = false;
      for (const button of buttons) {
        button.disabled = true;
      }
    } else {
      note.textContent = '';
      note.hidden = true;
      for (const button of buttons) {
        button.disabled = false;
      }
    }
  }

  return { element: root, sync };
}
