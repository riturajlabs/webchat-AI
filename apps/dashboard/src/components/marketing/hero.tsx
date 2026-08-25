import Link from 'next/link';
import { ArrowRight, BookOpen, Clock, Code2, ShieldCheck, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { WidgetShowcase } from './widget-showcase';

const TRUST_POINTS = [
  { icon: Clock, label: 'Live in minutes' },
  { icon: Code2, label: 'Zero code required' },
  { icon: ShieldCheck, label: 'Secure by default' },
];

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div
        className="absolute inset-0 -z-10 bg-gradient-to-b from-blue-600/[0.04] to-transparent"
        aria-hidden="true"
      />
      <div
        className="absolute left-1/2 top-0 h-[500px] w-[800px] -translate-x-1/2 -translate-y-1/3 rounded-full bg-brand-gradient opacity-[0.07] blur-[100px]"
        aria-hidden="true"
      />
      <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:py-28">
        <div className="flex flex-col items-start gap-5">
          <span className="inline-flex items-center gap-2 rounded-full border border-blue-600/20 bg-blue-600/5 px-3.5 py-1.5 text-xs font-semibold tracking-wide text-blue-700 dark:border-blue-400/20 dark:bg-blue-400/10 dark:text-blue-400">
            <Sparkles className="size-3.5" aria-hidden="true" />
            AI chatbot for your website
          </span>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-[3.25rem] lg:leading-[1.1]">
            Answer every visitor question{' '}
            <span className="relative whitespace-nowrap text-blue-600 dark:text-blue-400">
              automatically
              <span
                className="absolute -bottom-1 left-0 h-1.5 w-full rounded-full bg-brand-gradient"
                aria-hidden="true"
              />
            </span>
          </h1>
          <p className="max-w-lg text-base leading-relaxed text-muted-foreground sm:text-lg">
            WebChat AI learns from your website content and gives every visitor a knowledgeable
            assistant — handling support, answering questions and guiding users 24/7.
          </p>
          <div className="flex flex-col gap-3 pt-1 sm:flex-row">
            <Button
              asChild
              size="lg"
              className="bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-600"
            >
              <Link href="/signup">
                Start Free
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/docs">
                <BookOpen aria-hidden="true" />
                View Docs
              </Link>
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            No credit card required · Free plan available
          </p>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 pt-3">
            {TRUST_POINTS.map(({ icon: Icon, label }) => (
              <span
                key={label}
                className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"
              >
                <Icon className="size-3.5 text-blue-600 dark:text-blue-400" aria-hidden="true" />
                {label}
              </span>
            ))}
          </div>
        </div>
        <WidgetShowcase />
      </div>
    </section>
  );
}
