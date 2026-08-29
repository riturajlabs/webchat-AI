/**
 * Marketing plan catalog — single front-end source of truth for plan tiers.
 *
 * Mirrors `backend/models/plan.py` exactly (ids, names, descriptions, limits,
 * `price_cents` in minor units). The dashboard billing/usage pages instead read
 * the authoritative registry live via `/api/billing/plans`; this static module
 * exists because the marketing pages are statically prerendered and cannot
 * await the API. `plan-catalog.test.ts` enforces the two never drift.
 *
 * Display-only fields (`features`, `cta`, `highlighted`) are presentation and
 * safe to tune; numeric/price fields MUST stay equal to the backend registry.
 */

import type { Plan, PlanLimits } from '@/features/usage/types';

/** ISO 4217 currency the backend prices self-serve plans in. */
export const PAYMENT_CURRENCY = 'INR';

/** Auth-aware CTAs the pricing cards may use (subset of `LandingAction`). */
export type PlanCta = 'start-free' | 'pricing-plan' | 'contact-sales';

export interface MarketingPlan extends Plan {
  /** Qualitative selling points shown under the derived numeric limits. */
  features: string[];
  /** Auth-aware CTA this card uses. */
  cta: PlanCta;
  /** Marks the "Most popular" card on the landing/pricing pages. */
  highlighted?: boolean;
}

export const PLAN_CATALOG: MarketingPlan[] = [
  {
    id: 'free',
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
    cta: 'start-free',
    highlighted: false,
    features: ['Basic analytics', 'Standard widget themes', 'Community support'],
  },
  {
    id: 'plus',
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
    currency: PAYMENT_CURRENCY,
    billing_period_days: 30,
    cta: 'pricing-plan',
    highlighted: false,
    features: ['Advanced analytics & insights', 'Custom branding & themes', 'Priority support'],
  },
  {
    id: 'pro',
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
    currency: PAYMENT_CURRENCY,
    billing_period_days: 30,
    cta: 'pricing-plan',
    highlighted: true,
    features: [
      'Advanced analytics & insights',
      'Custom branding & themes',
      'API access',
      'Priority support',
    ],
  },
  {
    id: 'enterprise',
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
    cta: 'contact-sales',
    highlighted: false,
    features: [
      'SSO & team management',
      'Custom integrations',
      'Dedicated support',
      'SLA guarantee',
    ],
  },
];

/** Numeric limit fields every plan carries (mirrors `backend/models/plan.py`). */
export type PlanLimitField = keyof PlanLimits;

/** Presentation metadata for the numeric plan limits on pricing cards. */
export const PLAN_LIMIT_FIELDS: { key: PlanLimitField; label: string; compact?: boolean }[] = [
  { key: 'max_websites', label: 'website' },
  { key: 'max_monthly_messages', label: 'messages / month' },
  { key: 'max_monthly_tokens', label: 'tokens / month', compact: true },
  { key: 'max_documents', label: 'documents' },
  { key: 'max_crawl_pages', label: 'crawl pages / month' },
];

/** Whether a plan is purchasable through self-serve checkout. */
export function isPurchasable(plan: Pick<Plan, 'price_cents'>): boolean {
  return (plan.price_cents ?? 0) > 0;
}
