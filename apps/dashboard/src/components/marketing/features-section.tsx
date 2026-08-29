import { ArrowRight, BarChart3, Bot, Globe, KeyRound, LibraryBig, Puzzle } from 'lucide-react';
import Link from 'next/link';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import { SectionHeading } from './section-heading';

const FEATURES = [
  {
    icon: Bot,
    title: 'AI Chatbot',
    description:
      'A website-specific assistant that answers visitor questions in minutes — activated with one script tag, no code required.',
    iconBg: 'bg-blue-600/10 group-hover:bg-blue-600/15',
    iconFg: 'text-blue-700 dark:text-blue-400',
    featured: true,
  },
  {
    icon: LibraryBig,
    title: 'RAG Knowledge Base',
    description:
      'Your pages are embedded into a vector index, so answers are grounded in your own content with cited sources.',
    iconBg: 'bg-amber-500/10 group-hover:bg-amber-500/15',
    iconFg: 'text-amber-700 dark:text-amber-400',
    featured: false,
  },
  {
    icon: Globe,
    title: 'Website Crawling',
    description:
      'Connect a URL and WebChat AI crawls and indexes your pages, keeping the knowledge base fresh.',
    iconBg: 'bg-emerald-600/10 group-hover:bg-emerald-600/15',
    iconFg: 'text-emerald-700 dark:text-emerald-400',
    featured: false,
  },
  {
    icon: BarChart3,
    title: 'Analytics',
    description:
      'Understand conversations, resolution rate, response times, token usage and user satisfaction.',
    iconBg: 'bg-violet-600/10 group-hover:bg-violet-600/15',
    iconFg: 'text-violet-700 dark:text-violet-400',
    featured: false,
  },
  {
    icon: Puzzle,
    title: 'Custom Widget',
    description:
      'Theme presets, brand colors, welcome messages and suggested questions with an instant live preview.',
    iconBg: 'bg-rose-600/10 group-hover:bg-rose-600/15',
    iconFg: 'text-rose-700 dark:text-rose-400',
    featured: false,
  },
  {
    icon: KeyRound,
    title: 'API Integration',
    description:
      'Create API keys to authenticate programmatic requests and build on top of your assistants.',
    iconBg: 'bg-sky-600/10 group-hover:bg-sky-600/15',
    iconFg: 'text-sky-700 dark:text-sky-400',
    featured: false,
  },
];

export function FeaturesSection() {
  return (
    <section id="features" className="scroll-mt-20 border-t border-border/60">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Features"
          title="Everything you need to launch an AI assistant"
          description="From crawling your first page to reading conversation analytics — one platform."
        />
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, description, iconBg, iconFg, featured }) => (
            <Card
              key={title}
              className={`group relative overflow-hidden border-border/60 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:border-blue-600/20 dark:hover:border-blue-400/20 ${
                featured ? 'sm:col-span-2 lg:col-span-2' : ''
              }`}
            >
              <CardHeader className={featured ? 'lg:flex-row lg:items-center lg:gap-5' : undefined}>
                <span
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-colors duration-200 ${iconBg} ${iconFg}`}
                >
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <CardTitle className="text-base">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
                  {description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="mt-8 text-center">
          <Link
            href="/docs"
            className="inline-flex items-center gap-1 text-sm font-medium text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
          >
            Explore the documentation
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </section>
  );
}
