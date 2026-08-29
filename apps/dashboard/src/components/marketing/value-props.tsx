import { Globe, Infinity as AlwaysOnIcon, Palette } from 'lucide-react';

import { SectionHeading } from './section-heading';

const VALUE_PROPS = [
  {
    icon: Globe,
    title: 'Answers from your content',
    description:
      'Your assistant responds using your website knowledge base — not generic filler. Every answer is grounded in the pages you publish.',
  },
  {
    icon: AlwaysOnIcon,
    title: 'Always available',
    description:
      'Give visitors instant answers around the clock, so your team can focus on the questions that actually need a human.',
  },
  {
    icon: Palette,
    title: 'Fully customizable',
    description:
      'Match the assistant to your brand with themes, colors, messaging and behavior — configured from one dashboard.',
  },
];

export function ValueProps() {
  return (
    <section className="border-t border-border/60">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Why WebChat AI"
          title="Everything your AI assistant needs."
          description="A focused toolkit for turning your website content into helpful, on-brand customer answers."
        />
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {VALUE_PROPS.map(({ icon: Icon, title, description }) => (
            <article
              key={title}
              className="group flex flex-col gap-4 rounded-xl border border-border/60 bg-card p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-600/20 hover:shadow-lg"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600/10 text-blue-700 transition-colors group-hover:bg-blue-600/15 dark:bg-blue-500/15 dark:text-blue-400">
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <h3 className="text-base font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
