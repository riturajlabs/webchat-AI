'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Bot,
  Database,
  Globe,
  LibraryBig,
  MessagesSquare,
  Plus,
  SlidersHorizontal,
} from 'lucide-react';

import { useAuth } from '@/features/auth/auth-context';
import { OnboardingChecklist } from '@/features/dashboard/onboarding-checklist';
import { StatusBadge } from '@/features/websites/status-badge';
import { useWebsites } from '@/features/websites/hooks';
import type { Website } from '@/features/websites/types';
import { useUsage } from '@/features/usage/hooks';
import { useConversations } from '@/features/conversations/hooks';
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

  const { data: usageData } = useUsage();
  const { data: conversationsData } = useConversations({ page: 1, perPage: 1 });

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

  const checklistSteps = [
    { label: 'Add website', href: '/websites', done: websites.length > 0 },
    { label: 'Crawl knowledge', href: '/knowledge', done: totalDocuments > 0 || totalPages > 0 },
    { label: 'Install widget', href: '/widget', done: websites.some((s) => s.status === 'ready') },
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
          <OnboardingChecklist steps={checklistSteps} />

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
