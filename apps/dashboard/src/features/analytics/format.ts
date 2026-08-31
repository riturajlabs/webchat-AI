/**
 * Display helpers for the analytics feature (Phase 11.3, rewrite).
 */

import type { DatePreset } from './types';

export const PRESET_OPTIONS: { value: Exclude<DatePreset, 'custom'>; label: string }[] = [
  { value: 7, label: '7 days' },
  { value: 30, label: '30 days' },
  { value: 90, label: '90 days' },
];

export const RANGE_OPTIONS: { value: DatePreset; label: string }[] = [
  ...PRESET_OPTIONS,
  { value: 'custom', label: 'Custom' },
];

/** `2026-08-11` -> `Aug 11`. */
export function formatDay(date: string): string {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return date;
  }
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(parsed);
}

/** `2026-08-11` -> `Aug 11, 2026`. */
export function formatDayLong(date: string): string {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return date;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(parsed);
}

/** 1234 -> "1,234"; compact for very large values. Shared helpers. */
import { formatCompact, formatNumber } from '@/lib/format';
export { formatCompact, formatNumber };

/** 1500 -> "1.5K"; 2.3M etc. */
export function formatTokens(value: number): string {
  return formatCompact(value);
}

/** 0.00105 -> "$0.001" (USD, per-million-token list prices). */
export function formatCost(value: number): string {
  if (!Number.isFinite(value)) {
    return '—';
  }
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
  }).format(value);
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return '—';
  }
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)}ms`;
  }
  if (seconds < 10) {
    return `${seconds.toFixed(2)}s`;
  }
  return `${seconds.toFixed(1)}s`;
}

/**
 * `4.27` -> `"4.3 / 5"`. Null/undefined/non-finite collapses to an em-dash
 * so an empty satisfaction card still renders.
 */
export function formatRating(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '—';
  }
  return `${value.toFixed(1)} / 5`;
}

/** `66.6667` -> `"67%"` (rounds to whole percent for card values). */
export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) {
    return '—';
  }
  return `${Math.round(value)}%`;
}

/**
 * Percentage change vs the previous period, `null` when either side is
 * unknown. A gain from a zero baseline yields `null` (rendered as "New" by
 * the page) instead of a nonsensical infinite percent.
 */
export function changePercent(
  current: number | null | undefined,
  previous: number | null | undefined,
): number | null {
  if (
    current === null ||
    current === undefined ||
    previous === null ||
    previous === undefined ||
    !Number.isFinite(current) ||
    !Number.isFinite(previous)
  ) {
    return null;
  }
  if (previous === 0) {
    return current > 0 ? null : 0;
  }
  return Math.round(((current - previous) / previous) * 100);
}

/** `23` -> `"+23%"`, `-5` -> `"-5%"`, `0` -> `"0%"`, unknown -> `"New"`. */
export function formatChange(change: number | null | undefined): string {
  if (change === null || change === undefined || !Number.isFinite(change)) {
    return 'New';
  }
  if (change > 0) {
    return `+${change}%`;
  }
  return `${change}%`;
}
