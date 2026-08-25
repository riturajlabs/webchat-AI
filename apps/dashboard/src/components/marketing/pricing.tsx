import Link from 'next/link';
import { Check, Zap } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { SectionHeading } from './section-heading';

const TIERS = [
  {
    name: 'Free',
    price: '$0',
    period: 'forever',
    description: 'Perfect for personal projects and testing.',
    features: [
      '1 website',
      '1,000 messages / month',
      'Basic analytics',
      'Standard widget themes',
      'Community support',
    ],
    cta: { label: 'Start Free', href: '/signup' },
    highlighted: false,
  },
  {
    name: 'Pro',
    price: '$29',
    period: '/month',
    description: 'For businesses that need a production-ready assistant.',
    features: [
      '5 websites',
      '25,000 messages / month',
      'Advanced analytics & insights',
      'Custom branding & themes',
      'Priority support',
      'API access',
    ],
    cta: { label: 'Get Started', href: '/signup' },
    highlighted: true,
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    description: 'For teams that need scale, security and support.',
    features: [
      'Unlimited websites',
      'Unlimited messages',
      'SSO & team management',
      'Custom integrations',
      'Dedicated support',
      'SLA guarantee',
    ],
    cta: { label: 'Contact Sales', href: '/signup' },
    highlighted: false,
  },
];

export function Pricing() {
  return (
    <section id="pricing" className="scroll-mt-20">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Pricing"
          title="Simple, transparent pricing"
          description="Start free and upgrade as your assistant grows. No hidden fees."
        />
        <div className="mt-12 grid gap-6 lg:grid-cols-3">
          {TIERS.map(({ name, price, period, description, features, cta, highlighted }) => (
            <div
              key={name}
              className={`relative flex flex-col overflow-hidden rounded-2xl border bg-card p-8 transition-all duration-200 ${
                highlighted
                  ? 'border-blue-600/40 shadow-xl ring-1 ring-blue-600/20'
                  : 'border-border/60 shadow-sm hover:shadow-md hover:border-border'
              }`}
            >
              {highlighted && (
                <span
                  className="absolute inset-x-0 top-0 h-1 bg-brand-gradient"
                  aria-hidden="true"
                />
              )}
              <div className="mb-6">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold">{name}</h3>
                  {highlighted && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-600/10 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">
                      <Zap className="size-3" aria-hidden="true" />
                      Popular
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{description}</p>
              </div>
              <div className="mb-6">
                <span className="text-4xl font-bold tracking-tight">{price}</span>
                {period && <span className="ml-1 text-sm text-muted-foreground">{period}</span>}
              </div>
              <ul className="mb-8 flex flex-1 flex-col gap-3">
                {features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2.5 text-sm">
                    <span
                      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                        highlighted
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
              <Button
                asChild
                className={`w-full ${
                  highlighted
                    ? 'bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-600'
                    : ''
                }`}
                variant={highlighted ? 'default' : 'outline'}
              >
                <Link href={cta.href}>{cta.label}</Link>
              </Button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
