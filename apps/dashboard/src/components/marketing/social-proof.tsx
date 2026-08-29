import { Boxes, GraduationCap, Handshake, Laptop, ShoppingBag, BookMarked } from 'lucide-react';

const CATEGORIES = [
  { icon: ShoppingBag, label: 'SaaS' },
  { icon: Boxes, label: 'E-commerce' },
  { icon: BookMarked, label: 'Education' },
  { icon: Handshake, label: 'Agencies' },
  { icon: Laptop, label: 'Documentation' },
  { icon: GraduationCap, label: 'Developer tools' },
];

export function SocialProof() {
  return (
    <section
      className="border-t border-border/60 bg-muted/30"
      aria-label="Who WebChat AI is built for"
    >
      <div className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 lg:py-16">
        <p className="text-center text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Built for teams that want AI support without the complexity
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-x-8 gap-y-4">
          {CATEGORIES.map(({ icon: Icon, label }) => (
            <span
              key={label}
              className="flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              <Icon className="size-4 text-blue-600/70 dark:text-blue-400" aria-hidden="true" />
              {label}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
