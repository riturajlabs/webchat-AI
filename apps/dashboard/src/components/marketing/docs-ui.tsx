import Link from 'next/link';
import Image from 'next/image';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Info,
  Lightbulb,
  TriangleAlert,
} from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export function BreadcrumbNav({ items }: { items: BreadcrumbItem[] }) {
  if (!items || items.length === 0) return null;

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex items-center gap-1.5 text-xs text-muted-foreground"
    >
      <Link href="/docs" className="transition-colors hover:text-foreground">
        Docs
      </Link>
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        return (
          <span key={index} className="inline-flex items-center gap-1.5">
            <ChevronRight className="size-3 text-muted-foreground/60" aria-hidden="true" />
            {item.href && !isLast ? (
              <Link href={item.href} className="transition-colors hover:text-foreground">
                {item.label}
              </Link>
            ) : (
              <span
                className={cn(isLast && 'font-medium text-foreground')}
                aria-current={isLast ? 'page' : undefined}
              >
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

export function DocHeader({
  title,
  lede,
  breadcrumb,
  breadcrumbs,
}: {
  title: string;
  lede: string;
  breadcrumb?: string;
  breadcrumbs?: BreadcrumbItem[];
}) {
  return (
    <header className="flex flex-col gap-2.5">
      {breadcrumbs ? (
        <BreadcrumbNav items={breadcrumbs} />
      ) : breadcrumb ? (
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {breadcrumb}
        </p>
      ) : null}
      <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">{title}</h1>
      <p className="max-w-2xl text-base text-muted-foreground">{lede}</p>
    </header>
  );
}

export function DocSection({
  title,
  description,
  id,
  children,
}: {
  title: string;
  description?: string;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="border-border/60 shadow-none">
      <CardHeader className="p-4 pb-1">
        {id ? (
          <h2
            id={id}
            className="scroll-mt-24 text-base font-semibold tracking-tight text-foreground"
          >
            {title}
          </h2>
        ) : (
          <CardTitle className="text-base text-foreground">{title}</CardTitle>
        )}
        {description ? <CardDescription className="text-sm">{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4 p-4 pt-2 [overflow-wrap:anywhere]">
        {children}
      </CardContent>
    </Card>
  );
}

export function SubHeading({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <h3
      id={id}
      className={cn('text-sm font-semibold tracking-tight text-foreground', id && 'scroll-mt-24')}
    >
      {children}
    </h3>
  );
}

export function StepCard({
  step,
  title,
  description,
  id,
  children,
}: {
  step: string;
  title: string;
  description?: string;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      id={id}
      className={cn(
        'relative flex flex-col gap-3 rounded-xl border border-border/70 bg-card p-5 shadow-xs transition-colors',
        id && 'scroll-mt-24',
      )}
    >
      <div className="flex items-start gap-3">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-blue-600/10 font-mono text-xs font-bold text-blue-600 dark:bg-blue-500/15 dark:text-blue-400">
          {step}
        </span>
        <div className="flex flex-col gap-0.5">
          <h2 className="text-base font-semibold tracking-tight text-foreground">{title}</h2>
          {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      <div className="flex flex-col gap-4 pt-1">{children}</div>
    </div>
  );
}

export function ScreenshotFrame({
  src,
  alt,
  caption,
  width = 1200,
  height = 700,
}: {
  src: string;
  alt: string;
  caption?: string;
  width?: number;
  height?: number;
}) {
  return (
    <figure className="my-2 flex flex-col gap-2">
      <div className="overflow-hidden rounded-xl border border-border/80 bg-muted/30 p-1.5 shadow-sm">
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          className="h-auto w-full rounded-lg object-cover"
        />
      </div>
      {caption ? (
        <figcaption className="text-center text-xs text-muted-foreground">{caption}</figcaption>
      ) : null}
    </figure>
  );
}

export function DiagramBox({
  title,
  description,
  children,
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="my-2 rounded-xl border border-border/70 bg-muted/20 p-5">
      {title ? (
        <div className="mb-4">
          <p className="text-sm font-semibold text-foreground">{title}</p>
          {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
        </div>
      ) : null}
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

export function Bullets({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc pl-5 text-sm text-muted-foreground">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}

export function Checklist({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="flex flex-col gap-2 text-sm text-muted-foreground">
      {items.map((item, index) => (
        <li key={index} className="flex items-start gap-2">
          <CheckCircle2
            className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400"
            aria-hidden="true"
          />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export function InlineCode({ children }: { children: React.ReactNode }) {
  return (
    <code className="break-words rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground [overflow-wrap:anywhere]">
      {children}
    </code>
  );
}

export type CalloutVariant = 'info' | 'tip' | 'warning' | 'important';

const CALLOUT_STYLES: Record<
  CalloutVariant,
  { border: string; bg: string; icon: React.ComponentType<{ className?: string }>; label: string }
> = {
  info: {
    border: 'border-blue-500/30',
    bg: 'bg-blue-500/5',
    icon: Info,
    label: 'Info',
  },
  tip: {
    border: 'border-emerald-500/30',
    bg: 'bg-emerald-500/5',
    icon: Lightbulb,
    label: 'Tip',
  },
  warning: {
    border: 'border-amber-500/30',
    bg: 'bg-amber-500/5',
    icon: TriangleAlert,
    label: 'Warning',
  },
  important: {
    border: 'border-red-500/30',
    bg: 'bg-red-500/5',
    icon: AlertCircle,
    label: 'Important',
  },
};

export function Callout({
  variant = 'info',
  title,
  children,
}: {
  variant?: CalloutVariant;
  title?: string;
  children: React.ReactNode;
}) {
  const { border, bg, icon: Icon, label } = CALLOUT_STYLES[variant];
  return (
    <div className={cn('rounded-lg border p-4 text-sm', border, bg)}>
      <p className="mb-1.5 flex items-center gap-2 font-medium text-foreground">
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        {title ?? label}
      </p>
      <div className="text-muted-foreground">{children}</div>
    </div>
  );
}

export type EndpointMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

const METHOD_STYLES: Record<EndpointMethod, string> = {
  GET: 'bg-blue-600/10 text-blue-700 dark:bg-blue-500/15 dark:text-blue-400',
  POST: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
  PATCH: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  DELETE: 'bg-red-500/10 text-red-700 dark:bg-red-500/15 dark:text-red-400',
};

export function EndpointBadge({ method }: { method: EndpointMethod }) {
  return (
    <span
      className={cn(
        'inline-block rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold',
        METHOD_STYLES[method],
      )}
    >
      {method}
    </span>
  );
}

export function RelatedDocs({
  links,
}: {
  links: { title: string; description: string; href: string }[];
}) {
  return (
    <section className="mt-8 flex flex-col gap-3 border-t border-border/60 pt-6">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Related documentation
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="group flex flex-col justify-between rounded-lg border border-border/70 p-4 transition-all hover:border-blue-600/50 hover:bg-muted/30"
          >
            <div>
              <p className="text-sm font-semibold text-foreground group-hover:text-blue-600 dark:group-hover:text-blue-400">
                {link.title}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">{link.description}</p>
            </div>
            <p className="mt-3 flex items-center gap-1 text-xs font-medium text-blue-600 dark:text-blue-400">
              Read guide{' '}
              <ArrowRight
                className="size-3 transition-transform group-hover:translate-x-0.5"
                aria-hidden="true"
              />
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}
