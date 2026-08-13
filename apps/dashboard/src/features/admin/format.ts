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
  return date.toLocaleDateString();
}

/** 1234 -> "1,234"; compact for very large values. */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined).format(value);
}

/** 1500 -> "1.5K". */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })
    .format(value)
    .toLowerCase();
}
