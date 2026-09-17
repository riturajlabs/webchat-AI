import Link from 'next/link';
import {
  ArrowRight,
  Blocks,
  BookOpen,
  Code2,
  Cpu,
  Database,
  FileText,
  LineChart,
  Rocket,
  Sliders,
  Terminal,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { DiagramBox, DocSection, RelatedDocs } from '@/components/marketing/docs-ui';
import { DOCS_NAV_GROUPS } from '@/features/docs/docs-nav';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/docs',
  title: 'Documentation',
  description:
    'Complete documentation for WebChat AI: connect your website or files, customize your assistant, integrate the widget, and monitor visitor conversations.',
});

const PATHS = [
  {
    role: 'Beginner',
    title: 'Set up your first AI assistant',
    description: 'Go from raw website content or uploaded files to a working assistant in 7 steps.',
    href: '/docs/quickstart',
    icon: Rocket,
    cta: 'Start quickstart',
  },
  {
    role: 'Developer',
    title: 'Integrate the widget into your application',
    description:
      'Embed the lightweight SDK into HTML, React, Next.js, or single-page apps with origin controls.',
    href: '/docs/embed',
    icon: Blocks,
    cta: 'View embed guide',
  },
  {
    role: 'Advanced',
    title: 'Understand RAG, security, and APIs',
    description:
      'Explore hybrid vector search, Reciprocal Rank Fusion, tenant isolation, and the REST API.',
    href: '/docs/rag-pipeline',
    icon: Cpu,
    cta: 'Explore RAG pipeline',
  },
];

const CATEGORY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  'Getting started': Rocket,
  Knowledge: Database,
  Widget: Sliders,
  Manage: LineChart,
  Developer: Terminal,
  Reference: FileText,
};

export default function DocsOverviewPage() {
  return (
    <div className="flex flex-col gap-12">
      {/* Hero Section */}
      <header className="flex flex-col gap-4 border-b border-border/60 pb-8">
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-blue-600/10 px-3 py-1 font-mono text-xs font-semibold text-blue-600 dark:bg-blue-500/15 dark:text-blue-400">
            Documentation
          </span>
          <span className="text-xs text-muted-foreground">Version 2.0</span>
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight text-foreground sm:text-5xl sm:leading-tight">
          Build, customize, and deploy your WebChat AI assistant.
        </h1>
        <p className="max-w-2xl text-base text-muted-foreground sm:text-lg">
          Learn how to connect your knowledge, configure your assistant, customize the widget, test
          your integration in staging, and deploy WebChat AI to your website.
        </p>
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Button
            asChild
            className="bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-600"
          >
            <Link href="/docs/quickstart">
              Get started <ArrowRight className="ml-1.5 size-4" aria-hidden="true" />
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/docs/embed">Widget Embed</Link>
          </Button>
          <Button asChild variant="ghost" className="text-muted-foreground hover:text-foreground">
            <Link href="/docs/api">
              <Code2 className="mr-1.5 size-4" aria-hidden="true" /> API Reference
            </Link>
          </Button>
        </div>
      </header>

      {/* Choose Your Path */}
      <section id="choose-path" className="flex flex-col gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Choose your path
          </p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-foreground">
            Start with the right guide for your role
          </h2>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {PATHS.map((path) => {
            const Icon = path.icon;
            return (
              <Link key={path.href} href={path.href} className="group">
                <Card className="flex h-full flex-col justify-between border-border/70 transition-all group-hover:border-blue-600/40 group-hover:shadow-md">
                  <CardHeader className="p-5 pb-2">
                    <div className="flex items-center justify-between">
                      <span className="flex size-9 items-center justify-center rounded-lg bg-blue-600/10 text-blue-600 dark:bg-blue-500/15 dark:text-blue-400">
                        <Icon className="size-4.5" aria-hidden="true" />
                      </span>
                      <span className="rounded bg-muted px-2 py-0.5 text-[11px] font-medium uppercase text-muted-foreground">
                        {path.role}
                      </span>
                    </div>
                    <CardTitle className="mt-3 text-base font-semibold group-hover:text-blue-600 dark:group-hover:text-blue-400">
                      {path.title}
                    </CardTitle>
                    <CardDescription className="text-xs leading-relaxed text-muted-foreground">
                      {path.description}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="p-5 pt-0">
                    <p className="flex items-center gap-1 text-xs font-semibold text-blue-600 dark:text-blue-400">
                      {path.cta}
                      <ArrowRight
                        className="size-3.5 transition-transform group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </p>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Documentation Categories */}
      <section id="documentation-topics" className="flex flex-col gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Explore Documentation
          </p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-foreground">
            Comprehensive platform documentation
          </h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {DOCS_NAV_GROUPS.map((group) => {
            const Icon = CATEGORY_ICONS[group.title] ?? BookOpen;
            return (
              <Card key={group.title} className="border-border/60 bg-card/60">
                <CardHeader className="p-4 pb-2">
                  <div className="flex items-center gap-2.5">
                    <span className="flex size-7 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <Icon className="size-3.5" aria-hidden="true" />
                    </span>
                    <CardTitle className="text-sm font-semibold">{group.title}</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-col gap-1.5 p-4 pt-1">
                  {group.items.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="group flex items-center justify-between rounded-md px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
                    >
                      <span className="font-medium group-hover:text-blue-600 dark:group-hover:text-blue-400">
                        {item.label}
                      </span>
                      <ArrowRight
                        className="size-3 opacity-0 transition-opacity group-hover:opacity-100"
                        aria-hidden="true"
                      />
                    </Link>
                  ))}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      {/* How WebChat AI Works */}
      <DocSection
        id="architecture-overview"
        title="How WebChat AI works"
        description="High-level architecture from ingestion to grounded answers."
      >
        <DiagramBox
          title="System Architecture"
          description="Multi-tenant backend with hybrid RAG and isolated client SDK"
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <p className="font-mono text-xs font-semibold text-blue-600 dark:text-blue-400">
                01. INGESTION
              </p>
              <p className="mt-1 text-xs font-medium text-foreground">Websites &amp; Documents</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Playwright/HTTP crawler for sites, or multi-format parser for PDFs, DOCX, MD, and
                TXT files.
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <p className="font-mono text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                02. HYBRID RAG
              </p>
              <p className="mt-1 text-xs font-medium text-foreground">Retrieval &amp; Grounding</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Cosine vector search + BM25-style lexical matching fused with Reciprocal Rank Fusion
                (RRF).
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <p className="font-mono text-xs font-semibold text-purple-600 dark:text-purple-400">
                03. EMBED WIDGET
              </p>
              <p className="mt-1 text-xs font-medium text-foreground">SDK &amp; Origin Security</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Self-contained 49 kB bundle rendering 11 theme presets and 10 fonts with domain
                allowlists.
              </p>
            </div>
          </div>
        </DiagramBox>

        <div className="mt-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            From knowledge to answers
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs font-medium">
            <span className="rounded-md border bg-muted/60 px-2.5 py-1 text-foreground">
              Knowledge Source
            </span>
            <span className="text-muted-foreground">&rarr;</span>
            <span className="rounded-md border bg-muted/60 px-2.5 py-1 text-foreground">
              Cleaning &amp; Chunking
            </span>
            <span className="text-muted-foreground">&rarr;</span>
            <span className="rounded-md border bg-muted/60 px-2.5 py-1 text-foreground">
              Vector Store
            </span>
            <span className="text-muted-foreground">&rarr;</span>
            <span className="rounded-md border bg-muted/60 px-2.5 py-1 text-foreground">
              Hybrid Retrieval
            </span>
            <span className="text-muted-foreground">&rarr;</span>
            <span className="rounded-md border border-blue-600/30 bg-blue-500/10 px-2.5 py-1 text-blue-600 dark:text-blue-400">
              Grounded Answer + Citations
            </span>
          </div>
        </div>
      </DocSection>

      {/* Product Video Walkthrough */}
      <section id="demo-video" className="flex flex-col gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Watch Walkthrough
          </p>
          <h2 className="mt-1 text-xl font-bold tracking-tight text-foreground">
            WebChat AI in action
          </h2>
          <p className="text-sm text-muted-foreground">
            See how an assistant is created, customized, tested, and embedded in under two minutes.
          </p>
        </div>
        <div className="overflow-hidden rounded-xl border border-border/80 bg-black/5 shadow-md dark:bg-black/30">
          <video
            controls
            preload="metadata"
            className="w-full aspect-video rounded-lg"
            src="/docs-assets/demo/app-demo.mp4"
          >
            Your browser does not support the video tag.
          </video>
        </div>
      </section>

      {/* Related Documentation */}
      <RelatedDocs
        links={[
          {
            title: 'Quickstart Tutorial',
            description: 'Step-by-step tutorial taking you from zero to a live embedded assistant.',
            href: '/docs/quickstart',
          },
          {
            title: 'Knowledge Sources',
            description: 'Compare website crawling, uploaded files, and mixed ingestion modes.',
            href: '/docs/knowledge-sources',
          },
          {
            title: 'Widget Embed Guide',
            description: 'Learn script tag integration, framework mounting, and allowed domains.',
            href: '/docs/embed',
          },
          {
            title: 'Customization Reference',
            description: 'Explore the 11 theme presets and 10 typography options.',
            href: '/docs/customization',
          },
        ]}
      />
    </div>
  );
}
