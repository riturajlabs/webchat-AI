import { Code2, Globe, Layers, Palette, Puzzle, Terminal } from 'lucide-react';

import { SectionHeading } from './section-heading';

const INTEGRATIONS = [
  { icon: Globe, name: 'Any Website', description: 'Paste the script tag into any HTML page' },
  { icon: Code2, name: 'React / Next.js', description: 'SDK with init() and mount() helpers' },
  { icon: Terminal, name: 'REST API', description: 'Build custom integrations with API keys' },
  { icon: Layers, name: 'WordPress', description: 'Drop-in embed for WordPress sites' },
  { icon: Puzzle, name: 'Custom CMS', description: 'Embed via script tag in any platform' },
  {
    icon: Palette,
    name: 'Theme Presets',
    description: '7 curated themes or bring your own colors',
  },
];

export function Integrations() {
  return (
    <section id="integrations" className="scroll-mt-20 border-t border-border/60">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Integrations"
          title="Works where your website lives"
          description="One script tag for any platform. SDKs for modern frameworks. API for everything else."
        />
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {INTEGRATIONS.map(({ icon: Icon, name, description }) => (
            <div
              key={name}
              className="group flex items-start gap-4 rounded-xl border border-border/60 bg-card p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-600/20 hover:shadow-md"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-600/10 text-blue-700 transition-colors group-hover:bg-blue-600/15 dark:bg-blue-500/15 dark:text-blue-400">
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <div>
                <p className="text-sm font-semibold">{name}</p>
                <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
