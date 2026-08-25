import { BarChart3, Bot, Globe, KeyRound, LibraryBig, Puzzle } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import { SectionHeading } from './section-heading';

const FEATURES = [
  {
    icon: Bot,
    title: 'AI Chatbot',
    description:
      'A website-specific assistant that answers visitor questions in minutes — no code required.',
  },
  {
    icon: LibraryBig,
    title: 'RAG Knowledge Base',
    description:
      'Your pages are embedded into a vector index, so answers are grounded in your own content.',
  },
  {
    icon: Globe,
    title: 'Website Crawling',
    description:
      'Connect a URL and WebChat AI crawls and indexes your pages, keeping the knowledge base fresh.',
  },
  {
    icon: BarChart3,
    title: 'Analytics',
    description:
      'Understand conversations, resolution rate, response times, token usage and user satisfaction.',
  },
  {
    icon: Puzzle,
    title: 'Custom Widget',
    description:
      'Theme presets, brand colors, welcome messages and suggested questions with an instant live preview.',
  },
  {
    icon: KeyRound,
    title: 'API Integration',
    description:
      'Create API keys to authenticate programmatic requests and build on top of your assistants.',
  },
];

export function FeaturesSection() {
  return (
    <section id="features" className="scroll-mt-20 border-t border-border/60 bg-muted/30">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Features"
          title="Everything you need to launch an AI assistant"
          description="From crawling your first page to reading conversation analytics — one platform."
        />
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, description }) => (
            <Card key={title} className="transition-shadow hover:shadow-md">
              <CardHeader>
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <CardTitle className="text-base">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
