import { ArrowRight, Link2, LibraryBig, Puzzle } from 'lucide-react';

import { SectionHeading } from './section-heading';

const STEPS = [
  {
    icon: Link2,
    title: 'Connect your website',
    description:
      'Add your website URL in the dashboard and WebChat AI starts crawling your pages in the background.',
  },
  {
    icon: LibraryBig,
    title: 'Build your knowledge base',
    description:
      'Crawled content is chunked and embedded into a vector index, so your assistant is grounded in your own pages.',
  },
  {
    icon: Puzzle,
    title: 'Embed your assistant',
    description:
      'Paste one script tag into your site. Your assistant appears as a chat widget, styled to match your brand.',
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20 border-t border-border/60 bg-muted/30">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="How it works"
          title="Go live in three simple steps."
          description="No infrastructure to run and no training data to collect — start from what you already have."
        />
        <ol className="relative mx-auto mt-14 max-w-5xl">
          {/* Desktop connecting line */}
          <div
            className="absolute left-0 right-0 top-7 hidden h-px bg-gradient-to-r from-transparent via-blue-600/40 to-transparent lg:block"
            aria-hidden="true"
          />
          <div className="grid gap-10 sm:grid-cols-3 sm:gap-6 lg:gap-8">
            {STEPS.map(({ icon: Icon, title, description }, index) => (
              <li key={title} className="relative flex flex-col items-center gap-4 text-center">
                <div className="relative z-10 flex h-14 w-14 items-center justify-center rounded-2xl border border-blue-600/20 bg-background text-blue-600 shadow-sm dark:text-blue-400">
                  <Icon className="size-6" aria-hidden="true" />
                  <span className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                    {index + 1}
                  </span>
                </div>
                <div className="max-w-xs">
                  <h3 className="text-base font-semibold">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {description}
                  </p>
                </div>
                {index < STEPS.length - 1 ? (
                  <ArrowRight
                    className="hidden size-4 rotate-0 text-muted-foreground lg:absolute lg:-right-4 lg:top-7 lg:block"
                    aria-hidden="true"
                  />
                ) : null}
              </li>
            ))}
          </div>
        </ol>
      </div>
    </section>
  );
}
