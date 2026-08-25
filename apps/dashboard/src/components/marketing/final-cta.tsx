import Link from 'next/link';
import { ArrowRight, Clock, Code2, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';

export function FinalCta() {
  return (
    <section className="border-t border-border/60">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <div className="relative overflow-hidden rounded-3xl bg-blue-600 px-6 py-16 text-center shadow-xl sm:px-16">
          <div
            className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-white/10 blur-3xl"
            aria-hidden="true"
          />
          <div
            className="absolute -bottom-24 -left-16 h-64 w-64 rounded-full bg-amber-400/20 blur-3xl"
            aria-hidden="true"
          />
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Ready to add an AI assistant to your website?
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base text-blue-100">
            Connect your site, train the knowledge base and embed the chatbot &mdash; in minutes,
            not days.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button
              asChild
              size="lg"
              className="bg-white text-blue-700 shadow-sm hover:bg-blue-50 focus-visible:ring-white"
            >
              <Link href="/signup">
                Start Free
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="outline"
              className="border-white/40 bg-transparent text-white hover:bg-white/10 hover:text-white"
            >
              <Link href="/docs">View Docs</Link>
            </Button>
          </div>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
            {[
              { icon: Clock, label: 'Live in minutes' },
              { icon: Code2, label: 'Zero code' },
              { icon: ShieldCheck, label: 'No credit card required' },
            ].map(({ icon: Icon, label }) => (
              <span
                key={label}
                className="flex items-center gap-1.5 text-xs font-medium text-blue-100"
              >
                <Icon className="size-3.5" aria-hidden="true" />
                {label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
