import Link from 'next/link';

import { Button } from '@/components/ui/button';

const TIERS = [
  {
    name: 'Starter',
    audience: 'For trying WebChat AI on a single site.',
    features: ['1 website', 'AI chat widget with RAG answers', 'Conversation analytics'],
  },
  {
    name: 'Growth',
    audience: 'For sites with steady traffic.',
    features: ['Multiple websites', 'Usage metering and quotas', 'Full widget customization'],
  },
  {
    name: 'Scale',
    audience: 'For teams running many assistants.',
    features: [
      'API keys for automation',
      'Priority crawling and retrieval',
      'Audit-ready administration',
    ],
  },
];

export function PricingTeaser() {
  return (
    <section id="pricing" className="scroll-mt-14 border-b">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 md:px-6 md:py-24">
        <div className="mb-10 flex max-w-2xl flex-col gap-3">
          <h2 className="font-sans text-3xl font-bold tracking-tight">Pricing</h2>
          <p className="text-muted-foreground">
            Plans scale with your usage. Final plan pricing is being finalized — you can start on
            the current beta today.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {TIERS.map((tier) => (
            <article key={tier.name} className="flex flex-col gap-4 rounded-lg border p-6">
              <div className="flex flex-col gap-1">
                <h3 className="font-medium">{tier.name}</h3>
                <p className="text-sm text-muted-foreground">{tier.audience}</p>
              </div>
              <ul className="flex flex-col gap-2 text-sm text-muted-foreground">
                {tier.features.map((feature) => (
                  <li key={feature}>{feature}</li>
                ))}
              </ul>
              <Button asChild variant="outline" className="mt-auto w-full">
                <Link href="/signup">Start free</Link>
              </Button>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
