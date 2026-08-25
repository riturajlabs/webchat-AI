import Link from 'next/link';
import { Check } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { SectionHeading } from './section-heading';

const INCLUDED = [
  'Website crawling & knowledge base',
  'Customizable chat widget',
  'Conversation analytics',
];

export function PricingTeaser() {
  return (
    <section id="pricing" className="scroll-mt-20">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Pricing"
          title="Start free, upgrade as you grow"
          description="Begin on the trial plan and move to a paid plan when your assistant takes off."
        />
        <div className="mx-auto mt-12 max-w-xl">
          <div className="relative overflow-hidden rounded-2xl border border-border/60 bg-card p-8 shadow-sm">
            <span
              className="absolute inset-x-0 top-0 h-1"
              style={{ backgroundImage: 'linear-gradient(90deg, #2563eb, #f59e0b)' }}
              aria-hidden="true"
            />
            <h3 className="text-lg font-semibold">Everything you need to launch</h3>
            <ul className="mt-4 flex flex-col gap-3">
              {INCLUDED.map((item) => (
                <li key={item} className="flex items-center gap-2.5 text-sm">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">
                    <Check className="size-3" aria-hidden="true" />
                  </span>
                  {item}
                </li>
              ))}
            </ul>
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <Button
                asChild
                className="bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-600"
              >
                <Link href="/signup">Get Started</Link>
              </Button>
              <Button asChild variant="ghost" className="text-muted-foreground">
                <Link href="/login">Sign in</Link>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
