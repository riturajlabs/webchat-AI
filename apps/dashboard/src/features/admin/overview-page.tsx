'use client';

import { Banknote, BarChart3, Building2, Gauge, MessagesSquare, Server, Users } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { AdminNav } from './admin-nav';
import { formatCents, formatCompact, formatNumber } from './format';
import { useAdminOverview } from './hooks';

function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof Building2;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardDescription>{label}</CardDescription>
        <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
      </CardHeader>
      <CardContent>
        <p className="font-sans text-3xl font-bold tracking-tight">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

function StatsSkeleton() {
  return (
    <div
      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
      role="status"
      aria-label="Loading stats"
    >
      {[0, 1, 2, 3, 4, 5, 6, 7].map((index) => (
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

/** Platform operations overview (Phase 15 `/api/admin/overview`). */
export function AdminOverviewPage() {
  const { data, isPending, isError, error, refetch } = useAdminOverview();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Admin overview</h1>
        <p className="text-sm text-muted-foreground">
          Platform KPIs, subscriptions, and revenue at a glance (Phase 15).
        </p>
      </div>

      <AdminNav />

      {isPending ? <StatsSkeleton /> : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">{error?.message ?? 'Failed to load stats.'}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError && data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Tenants"
              value={formatNumber(data.stats.tenants.total)}
              hint={`${data.stats.tenants.active} active · ${data.stats.tenants.suspended} suspended`}
              icon={Building2}
            />
            <KpiCard
              label="Users"
              value={formatNumber(data.stats.users.total)}
              hint={`${data.stats.users.active} active · ${data.stats.users.suspended} suspended`}
              icon={Users}
            />
            <KpiCard
              label="Active subscriptions"
              value={formatNumber(data.active_subscriptions)}
              hint={`${formatCents(data.total_revenue_cents, data.currency)} total collected`}
              icon={Banknote}
            />
            <KpiCard
              label="Revenue"
              value={formatCents(data.total_revenue_cents, data.currency)}
              hint={data.currency}
              icon={BarChart3}
            />
            <KpiCard
              label="Conversations"
              value={formatNumber(data.stats.usage.conversations)}
              hint={`${formatNumber(data.stats.usage.messages)} messages`}
              icon={MessagesSquare}
            />
            <KpiCard
              label="Tokens"
              value={formatCompact(data.stats.usage.total_tokens)}
              hint={`${formatCompact(data.stats.usage.input_tokens)} in · ${formatCompact(
                data.stats.usage.output_tokens,
              )} out`}
              icon={BarChart3}
            />
            <KpiCard
              label="Crawl jobs"
              value={formatNumber(data.stats.crawl_jobs.total)}
              hint={`${data.stats.crawl_jobs.active} active`}
              icon={Server}
            />
            <KpiCard
              label="Crawl failures"
              value={formatNumber(data.stats.crawl_jobs.failed)}
              hint={`${(data.stats.crawl_jobs.error_rate * 100).toFixed(1)}% error rate`}
              icon={Gauge}
            />
          </div>

          <div>
            <h2 className="mb-2 font-sans text-sm font-semibold text-muted-foreground">
              Storage at a glance
            </h2>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
              {Object.entries(data.counts).map(([key, value]) => (
                <div
                  key={key}
                  className="rounded-lg border bg-card p-3 shadow-sm"
                  data-testid={`count-${key}`}
                >
                  <p className="font-sans text-lg font-bold tracking-tight">
                    {formatNumber(value)}
                  </p>
                  <p className="text-xs text-muted-foreground">{key.replaceAll('_', ' ')}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
