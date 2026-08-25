import Link from 'next/link';
import { BookOpen } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { WidgetShowcase } from './widget-showcase';

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:py-24">
        <div className="flex flex-col items-start gap-6">
          <p className="inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-700 dark:text-amber-400">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
            AI chatbot for your website
          </p>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
            Turn your website content into an{' '}
            <span className="relative whitespace-nowrap text-blue-600 dark:text-blue-400">
              AI assistant
              <span
                className="absolute -bottom-1 left-0 h-1.5 w-full rounded-full"
                style={{ backgroundImage: 'linear-gradient(90deg, #2563eb, #f59e0b)' }}
                aria-hidden="true"
              />
            </span>
          </h1>
          <p className="max-w-xl text-base text-muted-foreground sm:text-lg">
            WebChat AI crawls your website, builds a retrieval-augmented knowledge base, and gives
            you an embeddable chat widget your visitors can talk to &mdash; live in minutes, zero
            code.
          </p>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Button
              asChild
              size="lg"
              className="bg-blue-600 text-white shadow-sm hover:bg-blue-700 focus-visible:ring-blue-600"
            >
              <Link href="/signup">Start Free</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/docs">
                <BookOpen aria-hidden="true" />
                View Docs
              </Link>
            </Button>
          </div>
        </div>
        <WidgetShowcase />
      </div>
    </section>
  );
}
