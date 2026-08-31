import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AnalyticsPage } from './analytics-page';
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
import type {
  AnalyticsOverview,
  AnalyticsSummary,
  FeedbackAnalytics,
  FeedbackSummary,
  QuestionCount,
  ResponseMetrics,
  TimeseriesPoint,
  TopWebsite,
} from './types';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

vi.mock('./hooks', () => ({
  useAnalyticsSummary: vi.fn(),
  useAnalyticsTimeseries: vi.fn(),
  useAnalyticsTopWebsites: vi.fn(),
  useAnalyticsPerformance: vi.fn(),
  useFeedbackSummary: vi.fn(),
  useAnalyticsOverview: vi.fn(),
  useAnalyticsQuestions: vi.fn(),
  useAnalyticsFeedback: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(),
}));

vi.mock('recharts', () => {
  const MockResponsiveContainer = ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  );
  const Chart = ({
    'data-testid': testId,
    children,
  }: {
    'data-testid'?: string;
    children?: React.ReactNode;
  }) => <div data-testid={testId}>{children}</div>;
  const Null = () => null;
  // BarChart components pass explicit `data-testid` props that the mock
  // honors; fall back to a rotating suffix if a future chart forgets one.
  let barChartIndex = 0;
  return {
    ResponsiveContainer: MockResponsiveContainer,
    ComposedChart: (props: Record<string, unknown>) => (
      <Chart {...props} data-testid="usage-trend-chart" />
    ),
    AreaChart: (props: Record<string, unknown>) => <Chart {...props} data-testid="token-chart" />,
    LineChart: (props: Record<string, unknown>) => (
      <Chart {...props} data-testid="rating-trend-chart" />
    ),
    BarChart: (props: Record<string, unknown>) => {
      const id = (props['data-testid'] as string | undefined) ?? `bar-chart-${barChartIndex}`;
      barChartIndex += 1;
      return <Chart {...props} data-testid={id} />;
    },
    Area: Null,
    Bar: Null,
    Line: Null,
    XAxis: Null,
    YAxis: Null,
    CartesianGrid: Null,
    Tooltip: Null,
  };
});

import { useRouter } from 'next/navigation';

import { useWebsites } from '@/features/websites/hooks';

const mockedUseWebsites = vi.mocked(useWebsites);
const mockedUseSummary = vi.mocked(useAnalyticsSummary);
const mockedUseTimeseries = vi.mocked(useAnalyticsTimeseries);
const mockedUseTopWebsites = vi.mocked(useAnalyticsTopWebsites);
const mockedUsePerformance = vi.mocked(useAnalyticsPerformance);
const mockedUseFeedback = vi.mocked(useFeedbackSummary);
const mockedUseOverview = vi.mocked(useAnalyticsOverview);
const mockedUseQuestions = vi.mocked(useAnalyticsQuestions);
const mockedUseFeedbackAnalytics = vi.mocked(useAnalyticsFeedback);
const mockedUseRouter = vi.mocked(useRouter);

const WEBSITES = [
  {
    id: 'site-1',
    name: 'Acme Inc',
    url: 'https://acme.example.com',
    status: 'ready',
    pages_indexed: 1,
    last_crawled_at: null,
    checksum: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    widget_id: 'widget-1',
    knowledge_status: 'ready',
    knowledge_documents: 1,
    knowledge_chunks: 5,
    last_knowledge_at: '2026-08-01T00:00:00Z',
  },
];

const SUMMARY: AnalyticsSummary = {
  total_conversations: 120,
  total_messages: 340,
  total_ai_responses: 100,
  total_tokens: 15000,
  total_input_tokens: 10000,
  total_output_tokens: 5000,
  estimated_cost: 0.0105,
  avg_response_time: 1.25,
  previous_conversations: 100,
  previous_messages: 300,
  previous_tokens: 12000,
  previous_avg_response_time: 1.5,
};

const TIMESERIES: TimeseriesPoint[] = [
  {
    date: '2026-08-05',
    conversations: 40,
    messages: 110,
    tokens: 5000,
    input_tokens: 3000,
    output_tokens: 2000,
  },
  {
    date: '2026-08-06',
    conversations: 80,
    messages: 230,
    tokens: 10000,
    input_tokens: 7000,
    output_tokens: 3000,
  },
];

const TOP_WEBSITES: TopWebsite[] = [
  { website_id: 'site-1', website_name: 'Acme Inc', conversations: 80, messages: 230 },
];

const PERFORMANCE: ResponseMetrics = {
  avg_response_time: 1.25,
  fastest_response_time: 0.4,
  slowest_response_time: 4.5,
  median_response_time: 1.0,
  p95_response_time: 3.2,
  distribution: {
    '<1s': 30,
    '1-2s': 40,
    '2-5s': 20,
    '5-10s': 8,
    '10s+': 2,
  },
};

const EMPTY_PERFORMANCE: ResponseMetrics = {
  avg_response_time: null,
  fastest_response_time: null,
  slowest_response_time: null,
  median_response_time: null,
  p95_response_time: null,
  distribution: {},
};

const FEEDBACK: FeedbackSummary = {
  total: 42,
  average_rating: 4.25,
  distribution: {
    '5': 22,
    '4': 12,
    '3': 4,
    '2': 2,
    '1': 2,
  },
};

const OVERVIEW: AnalyticsOverview = {
  total_conversations: 120,
  total_messages: 340,
  total_questions: 150,
  total_ai_responses: 100,
  successful_answers: 85,
  fallback_responses: 15,
  resolution_rate: 85,
  fallback_percentage: 15,
  avg_response_time: 1.25,
};

const QUESTIONS: QuestionCount[] = [
  { question: 'What courses are available?', count: 40 },
  { question: 'How do I reset my password?', count: 25 },
  { question: 'What are the pricing plans?', count: 10 },
];

const FEEDBACK_ANALYTICS: FeedbackAnalytics = {
  total: 42,
  positive: 34,
  negative: 4,
  neutral: 4,
  positive_percentage: 81,
  negative_percentage: 9.5,
  average_rating: 4.25,
  distribution: {
    '5': 22,
    '4': 12,
    '3': 4,
    '2': 2,
    '1': 2,
  },
  trend: [
    { date: '2026-08-05', average_rating: 4.0, ratings: 10 },
    { date: '2026-08-06', average_rating: 4.5, ratings: 12 },
  ],
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <AnalyticsPage />
    </QueryClientProvider>,
  );
}

function mockData() {
  mockedUseWebsites.mockReturnValue({
    data: WEBSITES,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useWebsites>);
  mockedUseSummary.mockReturnValue({
    data: SUMMARY,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAnalyticsSummary>);
  mockedUseTimeseries.mockReturnValue({
    data: TIMESERIES,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAnalyticsTimeseries>);
  mockedUseTopWebsites.mockReturnValue({
    data: TOP_WEBSITES,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAnalyticsTopWebsites>);
  mockedUsePerformance.mockReturnValue({
    data: PERFORMANCE,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAnalyticsPerformance>);
  mockedUseFeedback.mockReturnValue({
    data: FEEDBACK,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useFeedbackSummary>);
  mockedUseOverview.mockReturnValue({
    data: OVERVIEW,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAnalyticsOverview>);
  mockedUseQuestions.mockReturnValue({
    data: QUESTIONS,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAnalyticsQuestions>);
  mockedUseFeedbackAnalytics.mockReturnValue({
    data: FEEDBACK_ANALYTICS,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAnalyticsFeedback>);
}

beforeEach(() => {
  mockData();
  mockedUseRouter.mockReturnValue({ push: vi.fn() } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AnalyticsPage', () => {
  it('shows an empty state when there are no websites', () => {
    mockedUseWebsites.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useWebsites>);
    renderPage();
    expect(screen.getByText('No analytics yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add a website' })).toBeInTheDocument();
  });

  it('navigates to /websites from the empty state', () => {
    const push = vi.fn();
    mockedUseRouter.mockReturnValue({ push } as never);
    mockedUseWebsites.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useWebsites>);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Add a website' }));
    expect(push).toHaveBeenCalledWith('/websites');
  });

  it('shows a loading state while the summary is pending', () => {
    mockedUseSummary.mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useAnalyticsSummary>);
    renderPage();
    expect(screen.getByRole('group', { name: 'Time range' })).toBeInTheDocument();
    expect(screen.getByLabelText('Loading analytics')).toBeInTheDocument();
    expect(screen.queryByText('Conversations')).not.toBeInTheDocument();
  });

  it('renders the KPI cards with previous-period deltas', () => {
    renderPage();
    expect(screen.getByText('Conversations')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('+20%')).toBeInTheDocument();
    expect(screen.getByText('Messages')).toBeInTheDocument();
    expect(screen.getByText('340')).toBeInTheDocument();
    expect(screen.getByText('+13%')).toBeInTheDocument();
    expect(screen.getByText('Tokens')).toBeInTheDocument();
    expect(screen.getAllByText('15k').length).toBeGreaterThan(0);
    expect(screen.getByText('+25%')).toBeInTheDocument();
    expect(screen.getByText('Avg response time')).toBeInTheDocument();
    expect(screen.getAllByText('1.25s').length).toBeGreaterThan(0);
    // Response time is inverted: lower is better, so a drop is an improvement
    // and still surfaced as "-17%".
    expect(screen.getByText('-17%')).toBeInTheDocument();
  });

  it('renders the secondary metric cards', () => {
    renderPage();
    expect(screen.getByText('Estimated cost')).toBeInTheDocument();
    expect(screen.getByText('$0.0105')).toBeInTheDocument();
    expect(screen.getByText('Resolution rate')).toBeInTheDocument();
    expect(screen.getByText('85%')).toBeInTheDocument();
    expect(screen.getByText('Fallback rate')).toBeInTheDocument();
    expect(screen.getByText('15%')).toBeInTheDocument();
    expect(screen.getAllByText('User satisfaction').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\d\.\d \/ 5/).length).toBeGreaterThan(0);
  });

  it('renders the charts once mounted', async () => {
    renderPage();
    expect(await screen.findByTestId('usage-trend-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('token-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('top-websites-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('popular-questions-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('response-histogram-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('feedback-distribution-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('rating-trend-chart')).toBeInTheDocument();
  });

  it('groups content into labelled sections for metric hierarchy', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'Key metrics' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Usage & engagement' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Quality & performance' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Quality insights' })).toBeInTheDocument();
  });

  it('shows chart placeholders while timeseries loads instead of empty states', () => {
    mockedUseTimeseries.mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useAnalyticsTimeseries>);
    renderPage();

    expect(screen.getAllByLabelText('Loading chart').length).toBeGreaterThan(0);
    expect(screen.queryByText('No conversations yet')).not.toBeInTheDocument();
  });

  it('switches the time range to a preset', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '30 days' }));
    const lastCall = mockedUseSummary.mock.calls[mockedUseSummary.mock.calls.length - 1];
    expect(lastCall[0]).toEqual({ preset: 30 });
  });

  it('selects a custom date range and passes it to the hooks', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Custom' }));
    fireEvent.change(screen.getByLabelText('Start date'), {
      target: { value: '2026-08-01' },
    });
    fireEvent.change(screen.getByLabelText('End date'), {
      target: { value: '2026-08-15' },
    });
    const lastCall = mockedUseSummary.mock.calls[mockedUseSummary.mock.calls.length - 1];
    expect(lastCall[0]).toEqual({
      preset: 'custom',
      start: '2026-08-01',
      end: '2026-08-15',
    });
  });

  it('asks for both dates before rendering an incomplete custom range', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Custom' }));
    expect(screen.getByText('Pick a date range')).toBeInTheDocument();
    expect(screen.queryByText('Conversations')).not.toBeInTheDocument();
  });

  it('filters by website', () => {
    renderPage();
    fireEvent.change(screen.getByLabelText('Filter by website'), {
      target: { value: 'site-1' },
    });
    const lastCall = mockedUseSummary.mock.calls[mockedUseSummary.mock.calls.length - 1];
    expect(lastCall[1]).toBe('site-1');
  });

  it('shows an error state with a retry action', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockedUseSummary.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      error: new Error('Failed to load analytics.'),
      refetch,
    } as unknown as ReturnType<typeof useAnalyticsSummary>);
    renderPage();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load analytics.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('refreshes from the filter bar', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockedUseSummary.mockReturnValue({
      data: SUMMARY,
      isPending: false,
      isError: false,
      error: null,
      refetch,
    } as unknown as ReturnType<typeof useAnalyticsSummary>);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh analytics' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('renders the response time stats (average, median, p95) and histogram', () => {
    renderPage();
    expect(screen.getByText('Response time')).toBeInTheDocument();
    expect(screen.getByText('Average')).toBeInTheDocument();
    expect(screen.getByText('Median')).toBeInTheDocument();
    expect(screen.getByText('1.00s')).toBeInTheDocument();
    expect(screen.getByText('P95')).toBeInTheDocument();
    expect(screen.getByText('3.20s')).toBeInTheDocument();
    expect(screen.getByText('Fastest 400ms')).toBeInTheDocument();
    expect(screen.getByText('Slowest 4.50s')).toBeInTheDocument();
    expect(screen.getByTestId('response-histogram-chart')).toBeInTheDocument();
  });

  it('shows an empty state for performance when there is no latency data', () => {
    mockedUsePerformance.mockReturnValue({
      data: EMPTY_PERFORMANCE,
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsPerformance>);
    renderPage();
    expect(screen.getByText('No response time data yet')).toBeInTheDocument();
    expect(screen.queryByTestId('response-histogram-chart')).not.toBeInTheDocument();
  });

  it('renders the satisfaction card with average, sentiment split, and distribution', async () => {
    renderPage();
    expect(screen.getByText('42 ratings in the selected period')).toBeInTheDocument();
    expect(screen.getByText('81%')).toBeInTheDocument();
    expect(screen.getByText('Positive (34)')).toBeInTheDocument();
    expect(screen.getByText('10%')).toBeInTheDocument();
    expect(screen.getByText('Negative (4)')).toBeInTheDocument();
    expect(await screen.findByTestId('feedback-distribution-chart')).toBeInTheDocument();
  });

  it('renders the rating trend line only when it spans at least two rated days', async () => {
    const { unmount } = renderPage();
    expect(await screen.findByTestId('rating-trend-chart')).toBeInTheDocument();
    unmount();

    mockedUseFeedbackAnalytics.mockReturnValue({
      data: {
        ...FEEDBACK_ANALYTICS,
        trend: [{ date: '2026-08-05', average_rating: 4.0, ratings: 10 }],
      },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsFeedback>);
    renderPage();
    expect(screen.queryByTestId('rating-trend-chart')).not.toBeInTheDocument();
    expect(screen.getAllByText('User satisfaction').length).toBeGreaterThan(0);
  });

  it('shows an empty state for the satisfaction chart when there are no ratings', () => {
    mockedUseFeedback.mockReturnValue({
      data: { total: 0, average_rating: null, distribution: {} },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useFeedbackSummary>);
    mockedUseFeedbackAnalytics.mockReturnValue({
      data: {
        total: 0,
        positive: 0,
        negative: 0,
        neutral: 0,
        positive_percentage: 0,
        negative_percentage: 0,
        average_rating: null,
        distribution: {},
        trend: [],
      },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsFeedback>);
    renderPage();
    expect(screen.getAllByText('User satisfaction').length).toBeGreaterThan(0);
    expect(screen.getByText('Awaiting first rating')).toBeInTheDocument();
    expect(screen.queryByTestId('feedback-distribution-chart')).not.toBeInTheDocument();
  });

  it('renders the popular questions chart with the most-asked questions', async () => {
    renderPage();
    expect(screen.getByText('Popular questions')).toBeInTheDocument();
    expect(await screen.findByTestId('popular-questions-chart')).toBeInTheDocument();
  });

  it('shows an empty state for popular questions when there are none', () => {
    mockedUseQuestions.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsQuestions>);
    renderPage();
    expect(screen.getByText('No questions yet')).toBeInTheDocument();
    expect(screen.queryByTestId('popular-questions-chart')).not.toBeInTheDocument();
  });

  it('shows an empty state instead of the usage charts when there is no activity', () => {
    mockedUseTimeseries.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsTimeseries>);
    renderPage();

    expect(screen.getByText('No conversations yet')).toBeInTheDocument();
    expect(
      screen.getByText('Install your widget on your website to start collecting chats.'),
    ).toBeInTheDocument();
    expect(screen.getByText('No token usage yet')).toBeInTheDocument();
    expect(screen.queryByTestId('usage-trend-chart')).not.toBeInTheDocument();
    expect(screen.queryByTestId('token-chart')).not.toBeInTheDocument();
  });

  it('builds quality insights only from real data', () => {
    renderPage();
    expect(screen.getByText('Busiest day')).toBeInTheDocument();
    expect(screen.getByText('Aug 6, 2026 with 230 messages')).toBeInTheDocument();
    expect(screen.getByText('Most common rating')).toBeInTheDocument();
    expect(screen.getByText('5★')).toBeInTheDocument();
    expect(screen.getByText('Fallback usage')).toBeInTheDocument();
    expect(screen.getByText('15% of answers used the no-context fallback')).toBeInTheDocument();
    expect(screen.getByText('Latency trend')).toBeInTheDocument();
    expect(
      screen.getByText('Average response time improved -17% vs the previous period'),
    ).toBeInTheDocument();
  });

  it('shows an insights empty state when there is no data to summarise', () => {
    mockedUseTimeseries.mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsTimeseries>);
    mockedUseFeedbackAnalytics.mockReturnValue({
      data: { ...FEEDBACK_ANALYTICS, total: 0, average_rating: null, distribution: {}, trend: [] },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsFeedback>);
    mockedUseOverview.mockReturnValue({
      data: { ...OVERVIEW, total_ai_responses: 0 },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsOverview>);
    mockedUseSummary.mockReturnValue({
      data: { ...SUMMARY, avg_response_time: null, previous_avg_response_time: null },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsSummary>);
    renderPage();
    expect(screen.getByText('Not enough data for insights yet')).toBeInTheDocument();
  });
});
