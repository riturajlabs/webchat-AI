import { describe, expect, it } from 'vitest';

import { formatDate, formatPrice, SUBSCRIPTION_STATUS_LABELS } from './types';

describe('formatDate', () => {
  it('formats a valid ISO date string', () => {
    const result = formatDate('2026-08-11T00:00:00Z');
    expect(result).toMatch(/Aug 11, 2026/);
  });

  it('formats a valid date-only string', () => {
    const result = formatDate('2026-01-15');
    expect(result).toMatch(/Jan 15, 2026/);
  });

  it('returns em-dash for an invalid date string', () => {
    expect(formatDate('not-a-date')).toBe('—');
  });

  it('returns em-dash for an empty string', () => {
    expect(formatDate('')).toBe('—');
  });

  it('returns em-dash for null', () => {
    expect(formatDate(null)).toBe('—');
  });

  it('returns em-dash for undefined', () => {
    expect(formatDate(undefined)).toBe('—');
  });
});

describe('formatPrice', () => {
  it('formats cents to currency', () => {
    expect(formatPrice(2900, 'USD')).toBe('$29.00');
  });

  it('returns "Custom" for null amount', () => {
    expect(formatPrice(null, 'USD')).toBe('Custom');
  });

  it('returns "Custom" for undefined amount', () => {
    expect(formatPrice(undefined as unknown as number | null, 'USD')).toBe('Custom');
  });
});

describe('SUBSCRIPTION_STATUS_LABELS', () => {
  it('maps known statuses to labels', () => {
    expect(SUBSCRIPTION_STATUS_LABELS.active).toBe('Active');
    expect(SUBSCRIPTION_STATUS_LABELS.trialing).toBe('Trial');
    expect(SUBSCRIPTION_STATUS_LABELS.cancelled).toBe('Cancelled');
    expect(SUBSCRIPTION_STATUS_LABELS.expired).toBe('Expired');
  });
});
