import type { Metadata } from 'next';
import Link from 'next/link';
import {
  ArrowRight,
  BookOpen,
  Blocks,
  ListTree,
  Rocket,
  ScrollText,
  SlidersHorizontal,
  ShieldCheck,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Bullets, DocHeader, DocSection } from '@/components/marketing/docs-ui';

export const metadata: Metadata = {
  title: 'Documentation',
  description:
    'Developer documentation for WebChat AI: install the chat widget, configure it and build on the API.',
};

const SECTIONS = [
  {
    href: '/docs/quickstart',
    icon: Rocket,
    title: 'Quickstart',
    description: 'Install the widget on your website in a few minutes.',
  },
  {
    href: '/docs/embed',
    icon: Blocks,
    title: 'Embed',
    description: 'Script tag usage, SDK init()/mount() and domain allowlists.',
  },
  {
    href: '/docs/configuration',
    icon: SlidersHorizontal,
    title: 'Configuration',
    description: 'Every widget option and the values it accepts.',
  },
  {
    href: '/docs/api',
    icon: ListTree,
    title: 'API',
    description: 'The REST endpoints behind the dashboard and widget.',
  },
  {
    href: '/docs/changelog',
    icon: ScrollText,
    title: 'Changelog',
    description: 'Notable documentation and integration changes.',
  },
];

export default function DocsOverviewPage() {
  return (
    <div className="flex flex-col gap-6">
      <DocHeader
        title="WebChat AI developer documentation"
        lede="Add the WebChat AI assistant to any website with a single script tag — then configure it, control where it renders and integrate it programmatically."
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SECTIONS.map(({ href, icon: Icon, title, description }) => (
          <Link key={href} href={href} className="group">
            <Card className="h-full transition-shadow group-hover:shadow-md">
              <CardHeader>
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">
                  <Icon className="size-4.5" aria-hidden="true" />
                </span>
                <CardTitle className="text-base">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{description}</p>
                <p className="mt-3 flex items-center gap-1 text-sm font-medium text-blue-600 dark:text-blue-400">
                  Open
                  <ArrowRight
                    className="size-3.5 transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <DocSection title="Security notes" description="How the widget is secured by default.">
        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">No secrets in the embed.</strong> The
              widget authenticates with short-lived, server-issued session tokens — never with the
              widget secret.
            </>,
            <>
              <strong className="font-medium text-foreground">Origin allowlist.</strong> The backend
              verifies the embedding page&apos;s <code className="font-mono text-xs">Origin</code>{' '}
              against <code className="font-mono text-xs">allowed_domains</code> on every public
              widget request.
            </>,
            <>
              <strong className="font-medium text-foreground">Rate limits.</strong> Per-widget,
              per-visitor and per-IP budgets bound abuse of sessions, chat and feedback.
            </>,
            <>
              <strong className="font-medium text-foreground">Anonymous by design.</strong> The
              visitor identifier is a non-PII cookie value; no localStorage or fingerprinting.
            </>,
            <>
              <strong className="font-medium text-foreground">Spam filtering.</strong> Incoming
              messages are screened before they reach the assistant pipeline.
            </>,
          ]}
        />
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="size-4 text-blue-600 dark:text-blue-400" aria-hidden="true" />
          Questions about embedding? Start with{' '}
          <Link
            href="/docs/embed"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed
          </Link>
          .
        </p>
      </DocSection>

      <DocSection title="Troubleshooting" description="Common issues and how to fix them.">
        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">Widget does not appear.</strong>{' '}
              Confirm the website is ready and the widget is enabled in the dashboard, then hard
              refresh your page. Config is cached for up to 5 minutes.
            </>,
            <>
              <strong className="font-medium text-foreground">403 Forbidden.</strong> The embedding
              origin is not in the allowlist. See{' '}
              <Link
                href="/docs/embed#domains"
                className="font-medium text-blue-600 hover:underline dark:text-blue-400"
              >
                Embed → Domain allowlist
              </Link>
              .
            </>,
          ]}
        />
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <BookOpen className="size-4 text-muted-foreground" aria-hidden="true" />
          More fixes live in each section — e.g. CSP errors under{' '}
          <Link
            href="/docs/embed#troubleshooting"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed → Troubleshooting
          </Link>
          .
        </p>
      </DocSection>
    </div>
  );
}
