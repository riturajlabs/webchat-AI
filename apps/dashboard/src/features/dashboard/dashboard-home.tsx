'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  CircleCheck,
  Database,
  Globe,
  KeyRound,
  LibraryBig,
  Loader2,
  Plus,
  Rocket,
  Server,
  Webhook,
  X,
} from 'lucide-react';

import { useAuth } from '@/features/auth/auth-context';
import { useSystemStatus } from '@/features/dashboard/use-system-status';
import { StatusBadge } from '@/features/websites/status-badge';
import { useWebsites } from '@/features/websites/hooks';
import type { Website } from '@/features/websites/types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';

function formatDate(value: string | null): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return date.toLocaleDateString();
}

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon: typeof Globe;
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

function QuickActions() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Quick actions</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <Button asChild variant="outline" className="justify-start">
          <Link href="/websites">
            <Plus aria-hidden="true" />
            Add website
          </Link>
        </Button>
        <Button asChild variant="outline" className="justify-start">
          <Link href="/websites">
            <Rocket aria-hidden="true" />
            Start a crawl
          </Link>
        </Button>
        <Button asChild variant="outline" className="justify-start">
          <Link href="/knowledge">
            <LibraryBig aria-hidden="true" />
            View knowledge base
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function CrawlStatusCard({ websites }: { websites: Website[] }) {
  const crawling = websites.filter(
    (site) =>
      site.status === 'pending' || site.status === 'crawling' || site.status === 'processing',
  ).length;
  const ready = websites.filter((site) => site.status === 'ready').length;
  const failed = websites.filter((site) => site.status === 'failed').length;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Crawl status</CardTitle>
        <CardDescription>Current state of connected websites.</CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="font-sans text-2xl font-bold tracking-tight">{crawling}</p>
          <p className="text-xs text-muted-foreground">In progress</p>
        </div>
        <div>
          <p className="font-sans text-2xl font-bold tracking-tight">{ready}</p>
          <p className="text-xs text-muted-foreground">Ready</p>
        </div>
        <div>
          <p className="font-sans text-2xl font-bold tracking-tight">{failed}</p>
          <p className="text-xs text-muted-foreground">Failed</p>
        </div>
      </CardContent>
    </Card>
  );
}

function SystemStatusCard() {
  const { data, isPending, isError, refetch } = useSystemStatus();

  const checks = [
    { label: 'API', ok: !isError, icon: Server },
    { label: 'Database', ok: data?.checks.database ?? false, icon: Database },
    { label: 'Redis', ok: data?.checks.redis ?? false, icon: Webhook },
  ];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <div>
          <CardTitle>System status</CardTitle>
          <CardDescription>Backend dependency health.</CardDescription>
        </div>
        {isPending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {checks.map(({ label, ok, icon: Icon }) => (
            <li key={label} className="flex items-center justify-between text-sm">
              <span className="inline-flex items-center gap-2 text-muted-foreground">
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </span>
              {isPending ? (
                <Skeleton className="h-4 w-16" />
              ) : ok ? (
                <span className="inline-flex items-center gap-1 text-green-700">
                  <CircleCheck className="size-4" aria-hidden="true" />
                  OK
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-destructive">
                  <X className="size-4" aria-hidden="true" />
                  Down
                </span>
              )}
            </li>
          ))}
        </ul>
        {isError ? (
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
            Retry
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function RecentWebsites({ websites }: { websites: Website[] }) {
  const recent = [...websites].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent websites</CardTitle>
        <CardDescription>Your latest connected websites.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col divide-y">
          {recent.map((website) => (
            <li key={website.id} className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <Link href="/websites" className="block truncate font-medium hover:underline">
                  {website.name}
                </Link>
                <p className="truncate text-sm text-muted-foreground">
                  {website.url} · last crawled {formatDate(website.last_crawled_at)}
                </p>
              </div>
              <StatusBadge status={website.status} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function DashboardHome() {
  const { user } = useAuth();
  const router = useRouter();
  const { data, isPending, isError, error, refetch } = useWebsites();

  const websites = data ?? [];

  const totalChunks = websites.reduce((sum, site) => sum + site.knowledge_chunks, 0);
  const totalDocuments = websites.reduce((sum, site) => sum + site.knowledge_documents, 0);
  const totalPages = websites.reduce((sum, site) => sum + site.pages_indexed, 0);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Welcome{user ? `, ${user.name}` : ''} — here is what is happening across your assistants.
        </p>
      </div>

      {isPending ? <StatGridSkeleton /> : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">
            {error?.message ?? 'Failed to load dashboard.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Websites"
              value={websites.length}
              hint="Connected assistants"
              icon={Globe}
            />
            <StatCard
              label="Knowledge chunks"
              value={totalChunks}
              hint="Across all websites"
              icon={LibraryBig}
            />
            <StatCard
              label="Documents embedded"
              value={totalDocuments}
              hint="In the vector index"
              icon={Database}
            />
            <StatCard
              label="Pages indexed"
              value={totalPages}
              hint="Total crawled pages"
              icon={KeyRound}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="flex flex-col gap-4 lg:col-span-2">
              {websites.length > 0 ? (
                <RecentWebsites websites={websites} />
              ) : (
                <EmptyState
                  title="No websites yet"
                  description="Connect your first website to start building its AI assistant."
                  actionLabel="Add your first website"
                  onAction={() => router.push('/websites')}
                />
              )}
              <SystemStatusCard />
            </div>
            <div className="flex flex-col gap-4">
              <QuickActions />
              {websites.length > 0 ? <CrawlStatusCard websites={websites} /> : null}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
