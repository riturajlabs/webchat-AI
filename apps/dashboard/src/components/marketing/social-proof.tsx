import { Clock, Code2, ShieldCheck } from 'lucide-react';

const TRUST_POINTS = [
  {
    icon: Clock,
    title: 'Setup in minutes',
    description: 'Paste one script tag and your assistant is live — no deployment pipeline needed.',
  },
  {
    icon: Code2,
    title: 'Zero code required',
    description: 'Connect your website URL and the knowledge base builds itself automatically.',
  },
  {
    icon: ShieldCheck,
    title: 'Secure by default',
    description:
      'No secrets ship to the browser. Session tokens are short-lived and server-issued.',
  },
];

export function SocialProof() {
  return (
    <section
      className="border-t border-border/60 bg-muted/30"
      aria-label="Why teams choose WebChat AI"
    >
      <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 lg:py-20">
        <p className="mb-10 text-center text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Why teams choose WebChat AI
        </p>
        <div className="grid gap-6 sm:grid-cols-3">
          {TRUST_POINTS.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="flex flex-col items-center gap-3 rounded-xl border border-border/60 bg-card px-6 py-8 text-center shadow-sm transition-shadow hover:shadow-md"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <h3 className="text-sm font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
