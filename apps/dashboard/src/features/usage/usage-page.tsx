'use client';

import Link from 'next/link';
import { CreditCard, FileText, Gauge, MessagesSquare } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { formatCompact, formatNumber } from '@/lib/format';

import { useUsage } from './hooks';
import { USAGE_LIMIT_LABELS } from './types';
import type { UsageMetric } from './types';

const WARNING_THRESHOLD = 80;

function SectionHeading({
  id,
  children,
  description,
}: {
  id: string;
  children: React.ReactNode;
  description?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <h2 id={id} className="font-sans text-lg font-semibold tracking-tight">
        {children}
      </h2>
      {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
    </div>
  );
}

function Header() {
  return (
    <PageHeader
      title="Usage & Billing"
      description="Your plan, limits, and consumption this month."
    />
  );
}

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof MessagesSquare;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardDescription>{label}</CardDescription>
        <Icon className="size-4 text-blue-600" aria-hidden="true" />
      </CardHeader>
      <CardContent>
        <p className="font-sans text-3xl font-bold tabular-nums tracking-tight">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

function StatGridSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((index) => (
        <Card key={index}>
          <CardHeader>
            <Skeleton className="h-4 w-24" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-8 w-16" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function LimitBar({ metric }: { metric: UsageMetric }) {
  if (metric.limit === null) {
    return (
      <div className="space-y-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-sm font-medium">
            {USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric}
          </p>
          <p className="text-xs text-muted-foreground">Unlimited</p>
        </div>
      </div>
    );
  }
  const percent = metric.percent ?? 0;
  const width = Math.min(100, percent);
  const nearLimit = percent >= WARNING_THRESHOLD;
  const barColor = nearLimit ? 'bg-amber-500' : 'bg-blue-600';
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric}</p>
        <p className="text-xs text-muted-foreground">
          {formatNumber(metric.used)} / {formatNumber(metric.limit)}
          {nearLimit ? <span className="ml-1 font-medium text-amber-600">· near limit</span> : null}
        </p>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(width)}
        aria-label={`${USAGE_LIMIT_LABELS[metric.metric] ?? metric.metric} usage`}
      >
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

export function UsagePage() {
  const { data: usage, isPending, isError, error, refetch } = useUsage();

  return (
    <div className="flex flex-col gap-8">
      <Header />

      {isPending ? <StatGridSkeleton /> : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load usage.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError && usage ? (
        <>
          <section aria-labelledby="current-usage-heading" className="flex flex-col gap-3">
            <SectionHeading
              id="current-usage-heading"
              description="Totals across every website you manage for the current calendar month."
            >
              Current usage
            </SectionHeading>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Messages used"
                value={formatNumber(usage.usage.messages_sent)}
                hint={
                  usage.plan.limits.max_monthly_messages === null
                    ? 'Unlimited this month'
                    : `Of ${formatNumber(usage.plan.limits.max_monthly_messages)} this month`
                }
                icon={MessagesSquare}
              />
              <StatCard
                label="Tokens used"
                value={formatCompact(usage.usage.tokens_used)}
                hint={
                  usage.plan.limits.max_monthly_tokens === null
                    ? 'Unlimited this month'
                    : `Of ${formatCompact(usage.plan.limits.max_monthly_tokens)} this month`
                }
                icon={Gauge}
              />
              <StatCard
                label="Documents"
                value={formatNumber(usage.usage.documents)}
                hint={
                  usage.plan.limits.max_documents === null
                    ? 'Unlimited'
                    : `Of ${formatNumber(usage.plan.limits.max_documents)} indexed`
                }
                icon={FileText}
              />
              <StatCard
                label="Current plan"
                value={usage.plan.name}
                hint={usage.plan.description}
                icon={CreditCard}
              />
            </div>
          </section>

          <section aria-labelledby="limits-heading" className="flex flex-col gap-3">
            <SectionHeading
              id="limits-heading"
              description={`How close each metric is to its plan allowance. Bars turn amber once usage passes ${WARNING_THRESHOLD}%.`}
            >
              Limits
            </SectionHeading>
            <Card>
              <CardHeader>
                <CardTitle>Monthly limits</CardTitle>
                <CardDescription>
                  Consumption against the {usage.plan.name} plan this calendar month.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-6 sm:grid-cols-2">
                {usage.limits.map((metric) => (
                  <LimitBar key={metric.metric} metric={metric} />
                ))}
              </CardContent>
            </Card>
          </section>

          <section aria-labelledby="trends-heading" className="flex flex-col gap-3">
            <SectionHeading
              id="trends-heading"
              description="Month-to-date activity across your assistants."
            >
              Consumption trends
            </SectionHeading>
            <Card>
              <CardHeader>
                <CardTitle>Month-to-date activity</CardTitle>
                <CardDescription>
                  What your assistants have processed so far this calendar month. Historical trends
                  appear here as more data accumulates.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <dt className="text-xs text-muted-foreground">AI responses generated</dt>
                    <dd className="mt-1 font-sans text-xl font-bold tracking-tight">
                      {formatNumber(usage.usage.ai_responses)}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <dt className="text-xs text-muted-foreground">Messages received</dt>
                    <dd className="mt-1 font-sans text-xl font-bold tracking-tight">
                      {formatNumber(usage.usage.messages_sent)}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <dt className="text-xs text-muted-foreground">Documents created</dt>
                    <dd className="mt-1 font-sans text-xl font-bold tracking-tight">
                      {formatNumber(usage.usage.documents_created)}
                    </dd>
                  </div>
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <dt className="text-xs text-muted-foreground">Crawl pages used</dt>
                    <dd className="mt-1 font-sans text-xl font-bold tracking-tight">
                      {formatNumber(usage.usage.crawl_pages)}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </section>

          <section aria-labelledby="plan-info-heading" className="flex flex-col gap-3">
            <SectionHeading
              id="plan-info-heading"
              description="What your current subscription includes."
            >
              Plan information
            </SectionHeading>
            <Card>
              <CardHeader className="flex flex-row items-start justify-between gap-2">
                <div>
                  <CardTitle>{usage.plan.name}</CardTitle>
                  <CardDescription>{usage.plan.description}</CardDescription>
                </div>
                <Button asChild variant="outline">
                  <Link href="/billing">Manage billing</Link>
                </Button>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3 lg:grid-cols-5">
                  <div>
                    <dt className="text-xs text-muted-foreground">Websites</dt>
                    <dd className="text-sm font-medium">
                      {usage.plan.limits.max_websites === null
                        ? 'Unlimited'
                        : formatNumber(usage.plan.limits.max_websites)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Messages / mo</dt>
                    <dd className="text-sm font-medium">
                      {usage.plan.limits.max_monthly_messages === null
                        ? 'Unlimited'
                        : formatNumber(usage.plan.limits.max_monthly_messages)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Tokens / mo</dt>
                    <dd className="text-sm font-medium">
                      {usage.plan.limits.max_monthly_tokens === null
                        ? 'Unlimited'
                        : formatCompact(usage.plan.limits.max_monthly_tokens)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Documents</dt>
                    <dd className="text-sm font-medium">
                      {usage.plan.limits.max_documents === null
                        ? 'Unlimited'
                        : formatNumber(usage.plan.limits.max_documents)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Crawl pages / mo</dt>
                    <dd className="text-sm font-medium">
                      {usage.plan.limits.max_crawl_pages === null
                        ? 'Unlimited'
                        : formatNumber(usage.plan.limits.max_crawl_pages)}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </section>
        </>
      ) : null}
    </div>
  );
}
