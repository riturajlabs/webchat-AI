'use client';

import Link from 'next/link';
import { ArrowRight, CheckCircle2, Clock, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/features/auth/auth-context';
import { getLandingDestination } from '@/lib/landing-navigation';

const ASSURANCE = [
  { icon: CheckCircle2, label: 'No credit card required' },
  { icon: Clock, label: 'Setup in minutes' },
  { icon: ShieldCheck, label: 'Secure by default' },
];

export function FinalCta() {
  const { isAuthenticated } = useAuth();
  const startFreeHref = getLandingDestination('start-free', isAuthenticated);

  return (
    <section className="border-t border-border/60">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <div className="relative overflow-hidden rounded-3xl bg-blue-600 px-6 py-16 text-center shadow-xl sm:px-16">
          <div
            className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-white/10 blur-3xl"
            aria-hidden="true"
          />
          <div
            className="absolute -bottom-24 -left-16 h-64 w-64 rounded-full bg-indigo-400/20 blur-3xl"
            aria-hidden="true"
          />
          <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Ready to turn your website into an AI assistant?
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base text-blue-100">
            Connect your site, build your knowledge base and start helping visitors in minutes — not
            days.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button
              asChild
              size="lg"
              className="bg-white text-blue-700 shadow-sm transition-all duration-150 hover:-translate-y-0.5 hover:bg-blue-50 hover:shadow-md focus-visible:ring-white"
            >
              <Link href={startFreeHref}>
                {isAuthenticated ? 'Open Dashboard' : 'Start Free'}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="outline"
              className="border-white/40 bg-transparent text-white hover:bg-white/10 hover:text-white"
            >
              <Link href="/docs">View Documentation</Link>
            </Button>
          </div>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
            {ASSURANCE.map(({ icon: Icon, label }) => (
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
