import { AlertCircle, Info, Lightbulb, TriangleAlert } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export function DocHeader({
  title,
  lede,
  breadcrumb,
}: {
  title: string;
  lede: string;
  breadcrumb?: string;
}) {
  return (
    <header className="flex flex-col gap-2">
      {breadcrumb ? (
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {breadcrumb}
        </p>
      ) : null}
      <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
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
    <Card>
      <CardHeader className="p-4 pb-1">
        {id ? (
          <h2 id={id} className="scroll-mt-24 text-base font-semibold tracking-tight">
            {title}
          </h2>
        ) : (
          <CardTitle className="text-base">{title}</CardTitle>
        )}
        {description ? <CardDescription className="text-sm">{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4 p-4 pt-2 [overflow-wrap:anywhere]">
        {children}
      </CardContent>
    </Card>
  );
}

export function SubHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-sm font-medium text-muted-foreground">{children}</h2>;
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
