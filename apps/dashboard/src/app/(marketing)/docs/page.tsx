import type { Metadata } from 'next';
import Link from 'next/link';
import { BookOpen, Code2, Puzzle, Rocket, ScrollText, Terminal } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { SCRIPT_TAG } from '@/features/docs/content';

import { CodeBlock } from '@/features/docs/code-block';
import { DocsShell } from './_components/docs-shell';

export const metadata: Metadata = {
  title: 'Developer Documentation',
  description:
    'Add the WebChat AI assistant to any website: quickstart, embed script, widget configuration, REST API and changelog.',
};

const SECTIONS = [
  {
    href: '/docs/quickstart',
    icon: Rocket,
    title: 'Quickstart',
    description: 'From signup to a live chat widget in five steps.',
  },
  {
    href: '/docs/embed',
    icon: Code2,
    title: 'Embed',
    description: 'Hosted script tag, SDK usage, domain allowlist and security notes.',
  },
  {
    href: '/docs/configuration',
    icon: Puzzle,
    title: 'Configuration',
    description: 'Every widget option you can set from the dashboard or the API.',
  },
  {
    href: '/docs/api',
    icon: Terminal,
    title: 'API',
    description: 'REST endpoints for websites, conversations, analytics and API keys.',
  },
  {
    href: '/docs/changelog',
    icon: ScrollText,
    title: 'Changelog',
    description: 'What shipped recently across the platform and the widget.',
  },
];

export default function DocsIndexPage() {
  return (
    <DocsShell active="/docs">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <BookOpen aria-hidden="true" className="size-5 text-muted-foreground" />
          <h1 className="font-sans text-3xl font-bold tracking-tight">Developer documentation</h1>
        </div>
        <p className="max-w-2xl text-balance text-muted-foreground">
          Add the WebChat AI assistant to any website with a single script tag — no build step
          required.
        </p>
      </header>

      <section aria-label="Quick embed example" className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          The whole integration is one line before your closing{' '}
          <code className="font-mono text-xs">&lt;/body&gt;</code> tag:
        </p>
        <CodeBlock code={SCRIPT_TAG} language="html" copyLabel="Copy script tag" />
        <p className="text-sm text-muted-foreground">
          Grab your real widget id from the dashboard, or start with the{' '}
          <Link href="/docs/quickstart" className="text-primary underline">
            quickstart
          </Link>
          .
        </p>
      </section>

      <section
        aria-label="Documentation sections"
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {SECTIONS.map(({ href, icon: Icon, title, description }) => (
          <Link
            key={href}
            href={href}
            className="group flex flex-col gap-2 rounded-lg border p-5 transition-colors hover:bg-muted/40"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-md border">
              <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
            </span>
            <span className="font-medium">{title}</span>
            <span className="text-sm text-muted-foreground">{description}</span>
          </Link>
        ))}
      </section>

      <section className="flex flex-col items-start gap-3 rounded-lg border bg-muted/30 p-6 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-md text-sm text-muted-foreground">
          Don&apos;t have an account yet? Create one free, add your website, and the assistant is
          live in minutes.
        </p>
        <Button asChild>
          <Link href="/signup">Get Started</Link>
        </Button>
      </section>
    </DocsShell>
  );
}
