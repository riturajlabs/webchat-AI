'use client';

import { useState } from 'react';
import {
  BarChart3,
  Building2,
  Gauge,
  MessagesSquare,
  ScrollText,
  Server,
  ShieldCheck,
  Users,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { formatCompact, formatNumber, statusLabel } from './format';
import { useAdminStats } from './hooks';
import { TenantPanel } from './tenant-panel';
import { UserPanel } from './user-panel';
import { CrawlPanel } from './crawl-panel';
import { AuditPanel } from './audit-panel';

type AdminTab = 'tenants' | 'users' | 'crawl-jobs' | 'audit-log';

const TABS: { value: AdminTab; label: string; icon: typeof Building2 }[] = [
  { value: 'tenants', label: 'Tenants', icon: Building2 },
  { value: 'users', label: 'Users', icon: Users },
  { value: 'crawl-jobs', label: 'Crawl queue', icon: Server },
  { value: 'audit-log', label: 'Audit log', icon: ScrollText },
];

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

export function AdminPage() {
  const [tab, setTab] = useState<AdminTab>('tenants');
  const { data, isPending, isError, error, refetch } = useAdminStats();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Admin</h1>
        <p className="text-sm text-muted-foreground">
          Platform operations: tenants, users, crawl queue, and audit log (ADR-006).
        </p>
      </div>

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
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Tenants"
            value={formatNumber(data.tenants.total)}
            hint={`${data.tenants.active} active · ${data.tenants.suspended} suspended`}
            icon={Building2}
          />
          <KpiCard
            label="Users"
            value={formatNumber(data.users.total)}
            hint={`${data.users.active} active · ${data.users.suspended} suspended`}
            icon={Users}
          />
          <KpiCard
            label="Conversations"
            value={formatNumber(data.usage.conversations)}
            hint={`${formatNumber(data.usage.messages)} messages`}
            icon={MessagesSquare}
          />
          <KpiCard
            label="Tokens"
            value={formatCompact(data.usage.total_tokens)}
            hint={`${formatCompact(data.usage.input_tokens)} in · ${formatCompact(
              data.usage.output_tokens,
            )} out`}
            icon={BarChart3}
          />
          <KpiCard
            label="Crawl jobs"
            value={formatNumber(data.crawl_jobs.total)}
            hint={`${data.crawl_jobs.active} active`}
            icon={Server}
          />
          <KpiCard
            label="Crawl failures"
            value={formatNumber(data.crawl_jobs.failed)}
            hint={`${(data.crawl_jobs.error_rate * 100).toFixed(1)}% error rate`}
            icon={ShieldCheck}
          />
          <KpiCard
            label="Active tenants"
            value={formatNumber(data.tenants.active)}
            hint={statusLabel('active')}
            icon={Gauge}
          />
          <KpiCard
            label="Active users"
            value={formatNumber(data.users.active)}
            hint={statusLabel('active')}
            icon={Gauge}
          />
        </div>
      ) : null}

      <div role="tablist" aria-label="Admin sections" className="flex flex-wrap gap-1">
        {TABS.map(({ value, label, icon: Icon }) => (
          <Button
            key={value}
            type="button"
            variant={tab === value ? 'default' : 'outline'}
            size="sm"
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
          >
            <Icon aria-hidden="true" />
            {label}
          </Button>
        ))}
      </div>

      {tab === 'tenants' ? <TenantPanel /> : null}
      {tab === 'users' ? <UserPanel /> : null}
      {tab === 'crawl-jobs' ? <CrawlPanel /> : null}
      {tab === 'audit-log' ? <AuditPanel /> : null}
    </div>
  );
}
