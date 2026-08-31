'use client';

import type { ReactNode } from 'react';
import { Check, Zap } from 'lucide-react';

import { PLAN_LIMIT_FIELDS, type MarketingPlan, type PlanLimitField } from './plan-catalog';
import { formatPrice } from './types';
import { formatCompact, formatNumber } from '@/lib/format';
import type { PlanLimits } from '@/features/usage/types';

/** "1 website", "3 websites", "10,000 crawl pages / month", "Unlimited …". */
export function formatPlanLimit(limits: PlanLimits, key: PlanLimitField): string {
  const field = PLAN_LIMIT_FIELDS.find((entry) => entry.key === key)!;
  const value = limits[key];
  const label = key === 'max_websites' ? (value === 1 ? 'website' : 'websites') : field.label;
  if (value === null || value === undefined) {
    return `Unlimited ${key === 'max_websites' ? 'websites' : label}`;
  }
  const formatted = field.compact ? formatCompact(value) : formatNumber(value);
  return `${formatted} ${label}`;
}

export function PricingCard({ plan, footer }: { plan: MarketingPlan; footer: ReactNode }) {
  const price = formatPrice(plan.price_cents ?? null, plan.currency ?? 'INR');
  const period =
    plan.billing_period_days === 30 ? '/month' : plan.price_cents === 0 ? 'forever' : '';

  return (
    <div
      className={`relative flex flex-col overflow-hidden rounded-2xl border bg-card p-8 transition-all duration-200 ${
        plan.highlighted
          ? 'border-blue-600/40 shadow-xl ring-1 ring-blue-600/20'
          : 'border-border/60 shadow-sm hover:shadow-md hover:border-border'
      }`}
    >
      {plan.highlighted && (
        <span className="absolute inset-x-0 top-0 h-1 bg-brand-gradient" aria-hidden="true" />
      )}
      <div className="mb-6">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold">{plan.name}</h3>
          {plan.highlighted && (
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-600/10 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">
              <Zap className="size-3" aria-hidden="true" />
              Most popular
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{plan.description}</p>
      </div>
      <div className="mb-6">
        <span className="text-4xl font-bold tracking-tight">{price}</span>
        {period && <span className="ml-1 text-sm text-muted-foreground">{period}</span>}
      </div>
      <ul className="mb-8 flex flex-1 flex-col gap-3">
        {[
          ...PLAN_LIMIT_FIELDS.map(({ key }) => formatPlanLimit(plan.limits, key)),
          ...plan.features,
        ].map((feature) => (
          <li key={feature} className="flex items-start gap-2.5 text-sm">
            <span
              className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                plan.highlighted
                  ? 'bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400'
                  : 'bg-muted text-muted-foreground'
              }`}
            >
              <Check className="size-3" aria-hidden="true" />
            </span>
            {feature}
          </li>
        ))}
      </ul>
      {footer}
    </div>
  );
}
