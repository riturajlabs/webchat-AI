'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Bot,
  Circle,
  CircleCheckBig,
  CircleX,
  Database,
  Globe,
  LibraryBig,
  Loader2,
  MessagesSquare,
  Plus,
  Server,
  SlidersHorizontal,
} from 'lucide-react';

import { useAuth } from '@/features/auth/auth-context';
import { useSystemStatus } from '@/features/dashboard/use-system-status';
import { StatusBadge } from '@/features/websites/status-badge';
import { useWebsites } from '@/features/websites/hooks';
import type { Website } from '@/features/websites/types';
import { useUsage } from '@/features/usage/hooks';
import { useConversations } from '@/features/conversations/hooks';
import { useWidgetConfig } from '@/features/widget/hooks';
import type { WidgetConfig } from '@/features/widget/types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { Skeleton } from '@/components/ui/skeleton';
import { formatNumber } from '@/lib/format';

function formatDate(value: string | null): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return date.toLocaleDateString(undefined, { timeZone: 'UTC' });
}

function isWidgetCustomized(widget: WidgetConfig | undefined): boolean {
  if (!widget) {
    return false;
  }
  return (
    widget.theme_preset !== '' ||
    widget.welcome_message.trim().length > 0 ||
    widget.suggested_questions.length > 0 ||
    widget.logo_url !== null ||
    widget.avatar_url !== null ||
    widget.header_color !== null ||
    widget.background_color !== null
  );
}

const CHECKLIST_STEPS = [
  { label: 'Create website', href: '/websites' },
  { label: 'Crawl knowledge base', href: '/knowledge' },
  { label: 'Customize widget', href: '/widget' },
  { label: 'Install widget', href: '/widget' },
  { label: 'Test chatbot', href: '/conversations' },
] as const;

function OnboardingChecklist({ done }: { done: boolean[] }) {
  const completed = done.filter(Boolean).length;
  const percent = Math.round((completed / CHECKLIST_STEPS.length) * 100);
  const nextIndex = done.findIndex((stepDone) => !stepDone);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <div>
          <CardTitle>Getting started</CardTitle>
          <CardDescription>
            {completed === CHECKLIST_STEPS.length
              ? 'All set — your assistant is live.'
              : `${completed} of ${CHECKLIST_STEPS.length} steps complete`}
          </CardDescription>
        </div>
        <span className="text-sm font-medium text-muted-foreground">{percent}%</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={`${completed} of ${CHECKLIST_STEPS.length} setup steps complete`}
          aria-label="Setup progress"
          className="h-2 w-full overflow-hidden rounded-full bg-muted"
        >
          <div
            className="h-full rounded-full bg-blue-600 transition-all"
            style={{ width: `${percent}%` }}
          />
        </div>
        <ol aria-label="Setup steps" className="flex flex-col divide-y">
          {CHECKLIST_STEPS.map(({ label, href }, index) => {
            const stepDone = done[index] ?? false;
            const isNext = index === nextIndex;
            return (
              <li key={label} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex min-w-0 items-center gap-2.5 text-sm">
                  {stepDone ? (
                    <CircleCheckBig
                      className="size-4 shrink-0 text-blue-600 dark:text-blue-400"
                      aria-hidden="true"
                    />
                  ) : (
                    <Circle className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  )}
                  <span className={stepDone ? 'text-muted-foreground line-through' : 'font-medium'}>
                    {label}
                  </span>
                  {isNext ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
                      Up next
                    </span>
                  ) : null}
                </span>
                {!stepDone ? (
                  <Button
                    asChild
                    variant="ghost"
                    size="sm"
                    className="shrink-0 text-blue-600 dark:text-blue-400"
                  >
                    <Link href={href}>
                      Open
                      <span className="sr-only">{label}</span>
                    </Link>
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}

const QUICK_ACTIONS = [
  { href: '/websites', icon: Plus, label: 'Add Website' },
  { href: '/knowledge', icon: LibraryBig, label: 'Upload Knowledge' },
  { href: '/widget', icon: SlidersHorizontal, label: 'Customize Widget' },
  { href: '/conversations', icon: MessagesSquare, label: 'View Conversations' },
] as const;

function QuickActions() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Quick actions</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {QUICK_ACTIONS.map(({ href, icon: Icon, label }) => (
          <Button key={href} asChild variant="outline" className="justify-start">
            <Link href={href}>
              <Icon aria-hidden="true" />
              {label}
            </Link>
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}

interface OverviewStat {
  label: string;
  value: string;
  hint: string;
  icon: typeof Globe;
  unavailable?: boolean;
}

export function DashboardHome() {
  const router = useRouter();
  const { user } = useAuth();
  const { data: websitesData, isPending, isError, error, refetch } = useWebsites();

  const websites: Website[] = websitesData ?? [];
  const firstWebsiteId = websites[0]?.id ?? null;

  const { data: usageData } = useUsage();
  const { data: conversationsData } = useConversations({ page: 1, perPage: 1 });
  const { data: widgetResponse } = useWidgetConfig(firstWebsiteId);

  const totalChunks = websites.reduce((sum, site) => sum + site.knowledge_chunks, 0);
  const totalDocuments = websites.reduce((sum, site) => sum + site.knowledge_documents, 0);
  const totalPages = websites.reduce((sum, site) => sum + site.pages_indexed, 0);

  const crawling = websites.filter(
    (site) =>
      site.status === 'pending' || site.status === 'crawling' || site.status === 'processing',
  ).length;
  const ready = websites.filter((site) => site.status === 'ready').length;
  const failed = websites.filter((site) => site.status === 'failed').length;

  const conversationCount = conversationsData?.total;
  const messagesSent = usageData?.usage.messages_sent;

  const knowledgeEmpty = totalChunks === 0 && totalDocuments === 0 && totalPages === 0;

  const overviewStats: OverviewStat[] = [
    {
      label: 'Websites',
      value: String(websites.length),
      hint: 'Connected assistants',
      icon: Globe,
    },
    {
      label: 'Conversations',
      value: conversationCount === undefined ? '—' : formatNumber(conversationCount),
      hint:
        conversationCount === undefined
          ? 'Could not load conversations'
          : 'Visitor chats across all widgets',
      icon: MessagesSquare,
      unavailable: conversationCount === undefined,
    },
    {
      label: 'Knowledge base',
      value: knowledgeEmpty ? 'Empty' : formatNumber(totalChunks),
      hint: `${formatNumber(totalDocuments)} documents · ${formatNumber(totalPages)} pages indexed`,
      icon: Database,
    },
    {
      label: 'Messages sent',
      value: messagesSent === undefined ? '—' : formatNumber(messagesSent),
      hint:
        messagesSent === undefined
          ? 'Could not load usage'
          : `Plan: ${usageData?.plan.name ?? '—'}`,
      icon: Bot,
      unavailable: messagesSent === undefined,
    },
  ];

  const checklistDone = [
    websites.length > 0,
    totalDocuments > 0 || totalPages > 0,
    isWidgetCustomized(widgetResponse?.widget),
    (conversationCount ?? 0) > 0,
    (messagesSent ?? 0) > 0,
  ];

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <p className="text-sm font-medium text-muted-foreground">
          Welcome{user ? `, ${user.name}` : ''}
        </p>
        <h1 className="text-3xl font-bold tracking-tight">Build your AI assistant</h1>
        <p className="text-sm text-muted-foreground">
          Connect your website and train your chatbot.
        </p>
      </header>

      {isPending ? (
        <>
          <div className="flex flex-col gap-3" aria-hidden="true">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-24 w-full" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
            {[0, 1, 2, 3].map((index) => (
              <Card key={index}>
                <CardHeader>
                  <Skeleton className="h-4 w-24" />
                </CardHeader>
                <CardContent>
                  <Skeleton className="h-8 w-16" />
                  <Skeleton className="mt-2 h-3 w-28" />
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      ) : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load dashboard.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError ? (
        <>
          <OnboardingChecklist done={checklistDone} />

          <section aria-label="Product overview">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {overviewStats.map(({ label, value, hint, icon: Icon, unavailable }) => (
                <Card key={label}>
                  <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
                    <CardDescription>{label}</CardDescription>
                    <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
                  </CardHeader>
                  <CardContent>
                    <p className="text-3xl font-bold tracking-tight">{value}</p>
                    <p
                      className={
                        unavailable
                          ? 'mt-1 text-xs text-destructive'
                          : 'mt-1 text-xs text-muted-foreground'
                      }
                    >
                      {hint}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>

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
              {websites.length > 0 ? (
                <CrawlStatusCard crawling={crawling} ready={ready} failed={failed} />
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </div>
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

function CrawlStatusCard({
  crawling,
  ready,
  failed,
}: {
  crawling: number;
  ready: number;
  failed: number;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Crawl status</CardTitle>
        <CardDescription>Current state of connected websites.</CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="text-2xl font-bold tracking-tight">{crawling}</p>
          <p className="text-xs text-muted-foreground">In progress</p>
        </div>
        <div>
          <p className="text-2xl font-bold tracking-tight">{ready}</p>
          <p className="text-xs text-muted-foreground">Ready</p>
        </div>
        <div>
          <p className="text-2xl font-bold tracking-tight">{failed}</p>
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
    { label: 'Redis', ok: data?.checks.redis ?? false, icon: Globe },
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
        <ul role="status" aria-label="System health" className="flex flex-col gap-2">
          {checks.map(({ label, ok, icon: Icon }) => (
            <li key={label} className="flex items-center justify-between text-sm">
              <span className="inline-flex items-center gap-2 text-muted-foreground">
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </span>
              {isPending ? (
                <Skeleton className="h-4 w-16" />
              ) : ok ? (
                <span className="inline-flex items-center gap-1 text-green-700 dark:text-green-400">
                  <CircleCheckBig className="size-4" aria-hidden="true" />
                  OK
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-destructive">
                  <CircleX className="size-4" aria-hidden="true" />
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
