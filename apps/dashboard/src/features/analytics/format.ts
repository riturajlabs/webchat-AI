/**
 * Display helpers for the analytics feature (Phase 11.3).
 */

import type { AnalyticsRange } from './types';

export const RANGE_OPTIONS: { value: AnalyticsRange; label: string }[] = [
  { value: 7, label: '7 days' },
  { value: 30, label: '30 days' },
  { value: 90, label: '90 days' },
];

/** `2026-08-11` -> `Aug 11`. */
export function formatDay(date: string): string {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return date;
  }
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
}

/** 1234 -> "1,234"; compact for very large values. */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined).format(value);
}

/** 1500 -> "1.5K"; 2.3M etc. */
export function formatCompact(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })
    .format(value)
    .toLowerCase();
}

/** 0.00105 -> "$0.001" (USD, per-million-token list prices). */
export function formatCost(value: number): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
  }).format(value);
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '—';
  }
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`;
  }
  return `${seconds.toFixed(2)}s`;
}
