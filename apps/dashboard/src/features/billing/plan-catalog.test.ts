import { describe, expect, it } from 'vitest';

import { PLAN_CATALOG, PAYMENT_CURRENCY } from './plan-catalog';

/**
 * Contract test: the marketing catalog MUST stay equal to
 * `backend/models/plan.py` (ids, names, descriptions, limits, prices, currency)
 * so marketing, the pricing page, the dashboard billing UI and checkout never
 * show diverging tiers. If the backend registry changes, update this test and
 * the catalog together.
 */
describe('PLAN_CATALOG ↔ backend/models/plan.py contract', () => {
  it('contains exactly the registered plans in registry order', () => {
    expect(PLAN_CATALOG.map((p) => p.id)).toEqual(['free', 'plus', 'pro', 'enterprise']);
  });

  it('matches the free plan', () => {
    expect(PLAN_CATALOG[0]).toMatchObject({
      name: 'Free',
      description: 'For personal projects and evaluation.',
      limits: {
        max_websites: 1,
        max_monthly_messages: 1_000,
        max_monthly_tokens: 100_000,
        max_documents: 10,
        max_crawl_pages: 500,
      },
      price_cents: 0,
      currency: PAYMENT_CURRENCY,
    });
  });

  it('matches the plus plan', () => {
    expect(PLAN_CATALOG[1]).toMatchObject({
      name: 'Plus',
      description: 'For small teams with growing needs.',
      limits: {
        max_websites: 3,
        max_monthly_messages: 5_000,
        max_monthly_tokens: 500_000,
        max_documents: 50,
        max_crawl_pages: 2_000,
      },
      price_cents: 1_900,
      billing_period_days: 30,
      currency: PAYMENT_CURRENCY,
    });
  });

  it('matches the pro plan', () => {
    expect(PLAN_CATALOG[2]).toMatchObject({
      name: 'Pro',
      description: 'For growing teams with higher usage.',
      limits: {
        max_websites: 10,
        max_monthly_messages: 50_000,
        max_monthly_tokens: 2_000_000,
        max_documents: 200,
        max_crawl_pages: 10_000,
      },
      price_cents: 4_900,
      billing_period_days: 30,
      currency: PAYMENT_CURRENCY,
    });
  });

  it('matches the enterprise plan', () => {
    expect(PLAN_CATALOG[3]).toMatchObject({
      name: 'Enterprise',
      description: 'Custom limits for high-volume deployments.',
      limits: {
        max_websites: null,
        max_monthly_messages: null,
        max_monthly_tokens: null,
        max_documents: null,
        max_crawl_pages: null,
      },
      price_cents: null,
      currency: PAYMENT_CURRENCY,
    });
  });

  it('uses a single currency across the catalog', () => {
    expect(PLAN_CATALOG.map((p) => p.currency).every((c) => c === PAYMENT_CURRENCY)).toBe(true);
  });
});
