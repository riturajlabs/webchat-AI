/**
 * Display helpers for the admin feature (Phase 12.5, ADR-006).
 */

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  suspended: 'Suspended',
  pending: 'Pending',
  running: 'Running',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
  ready: 'Ready',
  owner: 'Owner',
  admin: 'Admin',
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

/** `2026-08-11T12:00:00Z` -> locale date + time. Null collapses to an em-dash. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

/** `2026-08-11T12:00:00Z` -> short date only. */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  // Calendar-date semantics: format in UTC so UTC-midnight timestamps render
  // the same day regardless of the viewer's timezone.
  return date.toLocaleDateString(undefined, { timeZone: 'UTC' });
}

/** 1234 -> "1,234"; compact for very large values. Shared helpers. */
export { formatCompact, formatNumber } from '@/lib/format';

/** Minor units (cents) -> localized currency, e.g. 2900 -> "$29.00". */
export function formatCents(cents: number | null | undefined, currency = 'USD'): string {
  if (cents == null) {
    return '—';
  }
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    currencyDisplay: 'narrowSymbol',
  }).format(cents / 100);
}
