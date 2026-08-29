import { BotMessageSquare, Gauge, LockKeyhole, ShieldCheck, Timer, Waypoints } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import { SectionHeading } from './section-heading';

const TRUST_POINTS = [
  {
    icon: ShieldCheck,
    title: 'Secure widget',
    description:
      'No secrets ship to the browser. The widget authenticates entirely with server-issued, short-lived tokens.',
  },
  {
    icon: Waypoints,
    title: 'Domain control',
    description:
      'An origin allowlist is verified on every widget request. An empty allowlist blocks embedding until you configure domains.',
  },
  {
    icon: BotMessageSquare,
    title: 'Knowledge-based answers',
    description: 'Responses are grounded in your crawled content, with spam screening built in.',
  },
  {
    icon: Timer,
    title: 'Short-lived sessions',
    description:
      'Widget sessions expire in minutes and slide on a validity window, so abandoned sessions cannot linger.',
  },
  {
    icon: Gauge,
    title: 'Rate limiting',
    description:
      'Per-widget, per-visitor and per-IP limits throttle abusive traffic and keep your assistant responsive.',
  },
  {
    icon: LockKeyhole,
    title: 'Tenant isolation',
    description:
      'Your content, conversations and credentials are scoped to your account — never shared across tenants.',
  },
];

export function TrustSecurity() {
  return (
    <section id="security" className="scroll-mt-20 border-t border-border/60 bg-muted/30">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Security"
          title="Built with security in mind."
          description="Security is part of the widget itself — not an afterthought."
        />
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TRUST_POINTS.map(({ icon: Icon, title, description }) => (
            <Card
              key={title}
              className="group border-border/60 transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-600/20 hover:shadow-md"
            >
              <CardHeader>
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600/10 text-blue-700 transition-colors group-hover:bg-blue-600/15 dark:bg-blue-500/15 dark:text-blue-400">
                  <Icon className="size-5" aria-hidden="true" />
                </span>
                <CardTitle className="text-base">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
