/**
 * Display helpers for the conversations feature (Phase 11.2).
 */

import type { ConversationStatus } from './types';

export const STATUS_LABELS: Record<ConversationStatus, string> = {
  answered: 'Answered',
  awaiting: 'Awaiting reply',
};

export const STATUS_STYLES: Record<ConversationStatus, string> = {
  answered: 'bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-400',
  awaiting: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-400',
};

/** Anonymous widget visitors carry a random cookie id; show a friendly label. */
export function visitorLabel(visitorId: string | null | undefined): string {
  if (!visitorId || visitorId === 'anon') {
    return 'Anonymous';
  }
  return visitorId;
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

export function formatMessageCount(count: number): string {
  return `${count} ${count === 1 ? 'message' : 'messages'}`;
}

export function formatResponseTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`;
  }
  return `${seconds.toFixed(1)}s`;
}
