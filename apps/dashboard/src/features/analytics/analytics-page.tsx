'use client';

import { useEffect, useMemo, useState } from 'react';
import nextDynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';
import { BarChart3, CircleDollarSign, Gauge, MessagesSquare, Star, Timer } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';

import { useWebsites } from '@/features/websites/hooks';

import {
  RANGE_OPTIONS,
  formatCompact,
  formatCost,
  formatNumber,
  formatPercent,
  formatRating,
  formatSeconds,
} from './format';
import {
  useAnalyticsFeedback,
  useAnalyticsOverview,
  useAnalyticsPerformance,
  useAnalyticsQuestions,
  useAnalyticsSummary,
  useAnalyticsTimeseries,
  useAnalyticsTopWebsites,
  useFeedbackSummary,
} from './hooks';
import type { AnalyticsRange } from './types';

/**
 * Chart rendering is code-split into `analytics-chart.tsx` so recharts stays
 * out of the main analytics bundle. Each chart loads client-side only with a
 * matching skeleton placeholder.
 */
const ActivityChart = nextDynamic(
  () => import('./analytics-chart').then((mod) => mod.ActivityChart),
  { ssr: false, loading: () => <ChartPlaceholder /> },
);
const TokenChart = nextDynamic(() => import('./analytics-chart').then((mod) => mod.TokenChart), {
  ssr: false,
  loading: () => <ChartPlaceholder />,
});
const TopWebsitesChart = nextDynamic(
  () => import('./analytics-chart').then((mod) => mod.TopWebsitesChart),
  { ssr: false, loading: () => <ChartPlaceholder height={320} /> },
);
const PopularQuestionsChart = nextDynamic(
  () => import('./analytics-chart').then((mod) => mod.PopularQuestionsChart),
  { ssr: false, loading: () => <ChartPlaceholder height={320} /> },
);
const FeedbackDistributionChart = nextDynamic(
  () => import('./analytics-chart').then((mod) => mod.FeedbackDistributionChart),
  { ssr: false, loading: () => <ChartPlaceholder height={220} /> },
);

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: typeof Timer;
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
      {[0, 1, 2, 3, 4, 5, 6].map((index) => (
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

function ChartShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function ChartPlaceholder({ height = 300 }: { height?: number }) {
  return (
    <div
      className="flex items-center justify-center"
      style={{ height }}
      role="status"
      aria-label="Loading chart"
    >
      <Skeleton className="h-4 w-40" />
    </div>
  );
}

export function AnalyticsPage() {
  const router = useRouter();
  const [days, setDays] = useState<AnalyticsRange>(7);
  const [websiteId, setWebsiteId] = useState('');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const { data: websitesData } = useWebsites();
  const websites = useMemo(() => websitesData ?? [], [websitesData]);

  const {
    data: summary,
    isPending: summaryPending,
    isError,
    error,
    refetch,
  } = useAnalyticsSummary(days, websiteId);
  const { data: timeseries } = useAnalyticsTimeseries(days, websiteId);
  const { data: topWebsites } = useAnalyticsTopWebsites(days);
  const { data: performance } = useAnalyticsPerformance(days, websiteId);
  const { data: feedback } = useFeedbackSummary(days, websiteId);
  const { data: overview } = useAnalyticsOverview(days, websiteId);
  const { data: questions } = useAnalyticsQuestions(days, websiteId);
  const { data: feedbackAnalytics } = useAnalyticsFeedback(days, websiteId);

  const activityData = useMemo(
    () =>
      (timeseries ?? []).map((point) => ({
        date: point.date,
        messages: point.messages,
        conversations: point.conversations,
      })),
    [timeseries],
  );

  const tokenData = useMemo(
    () =>
      (timeseries ?? []).map((point) => ({
        date: point.date,
        input_tokens: point.input_tokens,
        output_tokens: point.output_tokens,
      })),
    [timeseries],
  );

  const feedbackDistribution = useMemo(
    () =>
      [5, 4, 3, 2, 1].map((stars) => ({
        stars,
        count: feedback?.distribution[String(stars)] ?? 0,
      })),
    [feedback],
  );

  const rangeLabel = RANGE_OPTIONS.find((option) => option.value === days)?.label.toLowerCase();

  if (websites.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <Header />
        <EmptyState
          icon={BarChart3}
          title="No analytics yet"
          description="Connect your first website and start chatting to see usage analytics."
          actionLabel="Add a website"
          onAction={() => router.push('/websites')}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Header />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div role="group" aria-label="Time range" className="flex gap-1">
          {RANGE_OPTIONS.map((option) => (
            <Button
              key={option.value}
              type="button"
              variant={days === option.value ? 'default' : 'outline'}
              size="sm"
              onClick={() => setDays(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <div className="sm:w-64">
          <label htmlFor="analytics-website-filter" className="sr-only">
            Filter by website
          </label>
          <select
            id="analytics-website-filter"
            value={websiteId}
            onChange={(event) => setWebsiteId(event.target.value)}
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">All websites</option>
            {websites.map((website) => (
              <option key={website.id} value={website.id}>
                {website.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {summaryPending ? <StatGridSkeleton /> : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">
            {error?.message ?? 'Failed to load analytics.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!summaryPending && !isError && summary ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Conversations"
              value={formatNumber(summary.total_conversations)}
              hint={`Last ${rangeLabel}`}
              icon={MessagesSquare}
            />
            <StatCard
              label="Messages"
              value={formatNumber(summary.total_messages)}
              hint={`Last ${rangeLabel}`}
              icon={MessagesSquare}
            />
            <StatCard
              label="Resolution Rate"
              value={formatPercent(overview?.resolution_rate ?? 0)}
              hint={
                overview
                  ? `${formatNumber(overview.successful_answers)} of ${formatNumber(
                      overview.total_ai_responses,
                    )} answers resolved`
                  : 'Assistant answers'
              }
              icon={BarChart3}
            />
            <StatCard
              label="Avg response time"
              value={formatSeconds(overview?.avg_response_time ?? summary.avg_response_time)}
              hint="Assistant latency"
              icon={Timer}
            />
            <StatCard
              label="Fallback rate"
              value={formatPercent(overview?.fallback_percentage ?? 0)}
              hint={
                overview
                  ? `${formatNumber(overview.fallback_responses)} unanswered ${
                      overview.fallback_responses === 1 ? 'question' : 'questions'
                    }`
                  : 'No-context answers'
              }
              icon={Gauge}
            />
            <StatCard
              label="Tokens"
              value={formatCompact(summary.total_tokens)}
              hint={`${formatNumber(summary.total_input_tokens)} in / ${formatNumber(
                summary.total_output_tokens,
              )} out`}
              icon={Gauge}
            />
            <StatCard
              label="Estimated cost"
              value={formatCost(summary.estimated_cost)}
              hint="At list prices"
              icon={CircleDollarSign}
            />
            <StatCard
              label="User satisfaction"
              value={formatRating(feedback?.average_rating ?? null)}
              hint={
                feedback && feedback.total > 0
                  ? `${formatNumber(feedback.total)} rating${feedback.total === 1 ? '' : 's'}`
                  : 'No ratings yet'
              }
              icon={Star}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="flex flex-col gap-4 lg:col-span-2">
              <ChartShell
                title="Activity over time"
                description="Messages and conversations per day."
              >
                <ActivityChart data={activityData} mounted={mounted} />
              </ChartShell>
              <ChartShell
                title="Popular questions"
                description="Most-asked questions in the selected period."
              >
                {questions && questions.length > 0 ? (
                  <PopularQuestionsChart data={questions} mounted={mounted} />
                ) : (
                  <EmptyState
                    icon={BarChart3}
                    title="No questions yet"
                    description="Once visitors ask the assistant, the most common questions show up here."
                  />
                )}
              </ChartShell>
              <ChartShell title="Token usage" description="Input and output tokens per day.">
                <TokenChart data={tokenData} mounted={mounted} />
              </ChartShell>
            </div>
            <div className="flex flex-col gap-4">
              <ChartShell
                title="Top websites"
                description="Most active assistants by conversations."
              >
                <TopWebsitesChart
                  data={(topWebsites ?? []).map((item) => ({
                    website_name: item.website_name,
                    conversations: item.conversations,
                  }))}
                  mounted={mounted}
                />
              </ChartShell>
              <PerformanceCard
                avg={performance?.avg_response_time ?? null}
                fastest={performance?.fastest_response_time ?? null}
                slowest={performance?.slowest_response_time ?? null}
              />
              <ChartShell title="User satisfaction" description="How visitors rated the assistant.">
                {feedbackAnalytics && feedbackAnalytics.total > 0 ? (
                  <div className="flex flex-col gap-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="rounded-lg border border-border bg-muted/30 p-3">
                        <p className="font-sans text-lg font-bold tracking-tight text-emerald-600">
                          {formatPercent(feedbackAnalytics.positive_percentage)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Positive ({formatNumber(feedbackAnalytics.positive)})
                        </p>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/30 p-3">
                        <p className="font-sans text-lg font-bold tracking-tight text-rose-600">
                          {formatPercent(feedbackAnalytics.negative_percentage)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Negative ({formatNumber(feedbackAnalytics.negative)})
                        </p>
                      </div>
                    </div>
                    <FeedbackDistributionChart data={feedbackDistribution} mounted={mounted} />
                  </div>
                ) : (
                  <EmptyState
                    icon={Star}
                    title="Awaiting first rating"
                    description="Once visitors rate answers, the 1-5 star breakdown shows up here."
                  />
                )}
              </ChartShell>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

function PerformanceCard({
  avg,
  fastest,
  slowest,
}: {
  avg: number | null;
  fastest: number | null;
  slowest: number | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Response time</CardTitle>
        <CardDescription>Assistant latency across the selected period.</CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="font-sans text-xl font-bold tracking-tight">{formatSeconds(avg)}</p>
          <p className="text-xs text-muted-foreground">Average</p>
        </div>
        <div>
          <p className="font-sans text-xl font-bold tracking-tight">{formatSeconds(fastest)}</p>
          <p className="text-xs text-muted-foreground">Fastest</p>
        </div>
        <div>
          <p className="font-sans text-xl font-bold tracking-tight">{formatSeconds(slowest)}</p>
          <p className="text-xs text-muted-foreground">Slowest</p>
        </div>
      </CardContent>
    </Card>
  );
}

function Header() {
  return (
    <div>
      <h1 className="font-sans text-2xl font-bold tracking-tight">Analytics</h1>
      <p className="text-sm text-muted-foreground">
        Chat, token, and assistant-performance usage statistics.
      </p>
    </div>
  );
}
