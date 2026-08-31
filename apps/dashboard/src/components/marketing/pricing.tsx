'use client';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { PLAN_CATALOG, type PlanCta } from '@/features/billing/plan-catalog';
import { useAuth } from '@/features/auth/auth-context';
import { getLandingDestination } from '@/lib/landing-navigation';

import { SectionHeading } from './section-heading';
import { PricingCard } from '@/features/billing/pricing-card';

export function Pricing() {
  const { isAuthenticated } = useAuth();
  const labels: Record<PlanCta, string> = {
    'start-free': 'Start Free',
    'pricing-plan': isAuthenticated ? 'Manage plan' : 'Get Started',
    'contact-sales': 'Contact Sales',
  };

  return (
    <section id="pricing" className="scroll-mt-20 border-t border-border/60">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Pricing"
          title="Simple, transparent pricing"
          description="Start free and upgrade as your assistant grows. No hidden fees."
        />
        <div className="mt-12 grid items-stretch gap-6 lg:grid-cols-4">
          {PLAN_CATALOG.map((plan) => {
            const href = getLandingDestination(plan.cta, isAuthenticated);
            const label = labels[plan.cta];
            return (
              <PricingCard
                key={plan.id}
                plan={plan}
                footer={
                  <Button
                    asChild
                    className={`mt-auto w-full ${
                      plan.highlighted
                        ? 'bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-600'
                        : ''
                    }`}
                    variant={plan.highlighted ? 'default' : 'outline'}
                  >
                    <Link href={href}>{label}</Link>
                  </Button>
                }
              />
            );
          })}
        </div>
      </div>
    </section>
  );
}
