/**
 * Shared display formatting helpers (audit Phase F).
 *
 * These are the canonical implementations; feature-level `format.ts` modules
 * re-export them so existing import paths keep working.
 */

/** `2026-08-11T12:00:00Z` -> short locale date only. Null/invalid collapses to an em-dash. */
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
