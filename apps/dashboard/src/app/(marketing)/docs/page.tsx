import Link from 'next/link';
import {
  ArrowRight,
  Blocks,
  BookOpen,
  ListTree,
  Rocket,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Bullets, Callout, DocSection, InlineCode } from '@/components/marketing/docs-ui';
import { DOCS_WIDGET_ID } from '@/features/docs/content';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs',
  title: 'Documentation',
  description:
    'Developer documentation for WebChat AI: install the chat widget, configure it and build on the API.',
});

const SECTIONS = [
  {
    href: '/docs/quickstart',
    icon: Rocket,
    title: 'Quickstart',
    description: 'Go from an empty dashboard to a live chatbot on your site in minutes.',
    step: 'Start here',
  },
  {
    href: '/docs/embed',
    icon: Blocks,
    title: 'Embed',
    description:
      'Script tag usage, SDK init()/mount(), API origin overrides and domain allowlists.',
    step: '1 minute',
  },
  {
    href: '/docs/configuration',
    icon: SlidersHorizontal,
    title: 'Configuration',
    description: 'Every widget customization option and the values it accepts.',
    step: '2 minutes',
  },
  {
    href: '/docs/api',
    icon: ListTree,
    title: 'API reference',
    description: 'The REST endpoints behind the dashboard and the widget runtime.',
    step: 'Advanced',
  },
] as const;

export default function DocsOverviewPage() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Documentation
        </p>
        <h1 className="text-3xl font-bold tracking-tight">WebChat AI developer documentation</h1>
        <p className="max-w-2xl text-base text-muted-foreground">
          Add the WebChat AI assistant to any website with a single script tag — then configure it,
          control where it renders and integrate it programmatically.
        </p>
      </header>

      <Callout variant="tip" title="New here?">
        Start with the{' '}
        <Link
          href="/docs/quickstart"
          className="font-medium text-blue-600 hover:underline dark:text-blue-400"
        >
          Quickstart
        </Link>{' '}
        — it walks you from an empty dashboard to a working widget in a few steps.
      </Callout>

      <section id="getting-started" className="flex flex-col gap-4">
        <h2 className="scroll-mt-24 text-2xl font-semibold tracking-tight">Getting started</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {SECTIONS.map(({ href, icon: Icon, title, description, step }) => (
            <Link key={href} href={href} className="group">
              <Card className="h-full transition-shadow group-hover:shadow-md">
                <CardHeader>
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">
                    <Icon className="size-4.5" aria-hidden="true" />
                  </span>
                  <CardTitle className="flex items-center justify-between text-base">
                    {title}
                    <span className="text-xs font-normal text-muted-foreground">{step}</span>
                  </CardTitle>
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
      </section>

      <DocSection
        id="how-it-works"
        title="How the widget works"
        description="The pieces that come together when you embed an assistant."
      >
        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">Knowledge base.</strong> You register
              a website and WebChat AI crawls its pages and embeds the content so the assistant can
              answer from your own docs.
            </>,
            <>
              <strong className="font-medium text-foreground">Widget bundle.</strong> A single
              JavaScript file renders the launcher and chat UI on your page.
            </>,
            <>
              <strong className="font-medium text-foreground">Widget API.</strong> Visitor chat
              traffic runs against the widget runtime, authenticated with short-lived session
              tokens.
            </>,
            <>
              <strong className="font-medium text-foreground">Dashboard API.</strong> The same REST
              surface the dashboard uses is available to you for custom integrations.
            </>,
          ]}
        />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Documentation sections</caption>
            <tbody>
              {SECTIONS.map(({ href, title, description }) => (
                <tr key={href} className="border-b last:border-0">
                  <td className="py-2 pr-3 font-medium">
                    <Link href={href} className="text-blue-600 hover:underline dark:text-blue-400">
                      {title}
                    </Link>
                  </td>
                  <td className="py-2 text-muted-foreground">{description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DocSection>

      <DocSection
        id="security"
        title="Security model"
        description="How the widget is secured by default."
      >
        <Bullets
          items={[
            <>
              <strong className="font-medium text-foreground">No secrets in the embed.</strong> The
              widget authenticates with short-lived, server-issued session tokens — never with the
              widget secret. The snippet you paste carries only{' '}
              <InlineCode>data-widget-id={DOCS_WIDGET_ID}</InlineCode>.
            </>,
            <>
              <strong className="font-medium text-foreground">Origin allowlist.</strong> The backend
              verifies the embedding page&apos;s <InlineCode>Origin</InlineCode> against{' '}
              <InlineCode>allowed_domains</InlineCode> on every public widget request.
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
      </DocSection>

      <DocSection
        id="troubleshooting"
        title="Troubleshooting"
        description="Common issues and where to fix them."
      >
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
                Embed &rarr; Domain allowlist
              </Link>
              .
            </>,
          ]}
        />
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <BookOpen className="size-4 text-muted-foreground" aria-hidden="true" />
          More fixes (including CSP errors) live under{' '}
          <Link
            href="/docs/embed#troubleshooting"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed &rarr; Troubleshooting
          </Link>{' '}
          and the{' '}
          <Link
            href="/docs/api"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            API reference
          </Link>
          .
        </p>
      </DocSection>

      <DocSection
        id="whats-new"
        title="What's new"
        description="Follow the documentation and integration surface changes."
      >
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ScrollText className="size-4 text-muted-foreground" aria-hidden="true" />
          See the{' '}
          <Link
            href="/docs/changelog"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Changelog
          </Link>{' '}
          for the latest updates.
        </p>
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="size-4 text-blue-600 dark:text-blue-400" aria-hidden="true" />
          Questions about embedding? Start with the{' '}
          <Link
            href="/docs/embed"
            className="font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Embed
          </Link>{' '}
          guide.
        </p>
      </DocSection>
    </div>
  );
}
