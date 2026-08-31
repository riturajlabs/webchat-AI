/**
 * Shared display helpers used across dashboard features. Feature-specific
 * formatting stays in the feature; only generic helpers live here.
 *
 * Both helpers collapse non-finite input (NaN/±Infinity) to an em-dash so a
 * malformed metric can never surface as "NaN" in the UI.
 */

/** 1234 -> "1,234" (locale-aware grouping). NaN/Infinity -> "—". */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return '—';
  }
  return new Intl.NumberFormat(undefined).format(value);
}

/** 1500 -> "1.5k"; 2300000 -> "2.3m". NaN/Infinity -> "—". */
export function formatCompact(value: number): string {
  if (!Number.isFinite(value)) {
    return '—';
  }
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })
    .format(value)
    .toLowerCase();
}
