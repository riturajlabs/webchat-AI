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
  // The dashboard renders two BarCharts (top websites + feedback
  // distribution); both pass explicit `data-testid` props that the mock
  // honors. Fall back to a rotating suffix if a future chart forgets one.
  let barChartIndex = 0;
  return {
    ResponsiveContainer: MockResponsiveContainer,
    ComposedChart: (props: Record<string, unknown>) => (
      <Chart {...props} data-testid="activity-chart" />
    ),
    AreaChart: (props: Record<string, unknown>) => <Chart {...props} data-testid="token-chart" />,
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
    expect(screen.getByLabelText('Time range')).toBeInTheDocument();
    expect(screen.queryByText('Conversations')).not.toBeInTheDocument();
  });

  it('renders the summary metric cards', () => {
    renderPage();
    expect(screen.getByText('Conversations')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('Messages')).toBeInTheDocument();
    expect(screen.getByText('340')).toBeInTheDocument();
    expect(screen.getByText('Resolution Rate')).toBeInTheDocument();
    expect(screen.getByText('85%')).toBeInTheDocument();
    expect(screen.getByText('Fallback rate')).toBeInTheDocument();
    expect(screen.getByText('15%')).toBeInTheDocument();
    expect(screen.getByText('Estimated cost')).toBeInTheDocument();
    expect(screen.getByText('$0.0105')).toBeInTheDocument();
    expect(screen.getByText('Avg response time')).toBeInTheDocument();
    expect(screen.getAllByText('1.25s').length).toBeGreaterThan(0);
  });

  it('renders the charts once mounted', async () => {
    renderPage();
    expect(await screen.findByTestId('activity-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('token-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('top-websites-chart')).toBeInTheDocument();
    expect(await screen.findByTestId('popular-questions-chart')).toBeInTheDocument();
  });

  it('switches the time range', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: '30 days' }));
    const lastCall = mockedUseSummary.mock.calls[mockedUseSummary.mock.calls.length - 1];
    expect(lastCall[0]).toBe(30);
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

  it('renders response time statistics', () => {
    renderPage();
    expect(screen.getByText('Response time')).toBeInTheDocument();
    expect(screen.getByText('Average')).toBeInTheDocument();
    expect(screen.getAllByText('1.25s').length).toBeGreaterThan(0);
    expect(screen.getByText('Fastest')).toBeInTheDocument();
    expect(screen.getByText('400ms')).toBeInTheDocument();
    expect(screen.getByText('Slowest')).toBeInTheDocument();
    expect(screen.getByText('4.50s')).toBeInTheDocument();
  });

  it('renders the user satisfaction card with the average rating and total count', () => {
    renderPage();
    // Both the StatCard (description) and the ChartShell (title) use the
    // label "User satisfaction"; assert on the unique value + hint instead.
    expect(screen.getByText('4.3 / 5')).toBeInTheDocument();
    expect(screen.getByText('42 ratings')).toBeInTheDocument();
  });

  it('renders the 1-5 star distribution chart when ratings exist', async () => {
    renderPage();
    // The BarChart inside the FeedbackDistributionChart carries the test id.
    expect(await screen.findByTestId('feedback-distribution-chart')).toBeInTheDocument();
    // Empty case is suppressed — the EmptyState should not appear here.
    expect(screen.queryByText('Awaiting first rating')).not.toBeInTheDocument();
  });

  it('renders the positive/negative feedback sentiment split', () => {
    renderPage();
    expect(screen.getByText('81%')).toBeInTheDocument();
    expect(screen.getByText('Positive (34)')).toBeInTheDocument();
    expect(screen.getByText('10%')).toBeInTheDocument();
    expect(screen.getByText('Negative (4)')).toBeInTheDocument();
  });

  it('renders the popular questions chart with the most-asked questions', async () => {
    renderPage();
    expect(screen.getByText('Popular questions')).toBeInTheDocument();
    // Top row (ranked) is sorted desc and reversed for the vertical layout.
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

  it('falls back to a zero resolution rate when the overview has not loaded', () => {
    mockedUseOverview.mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsOverview>);
    renderPage();
    expect(screen.getAllByText('0%').length).toBeGreaterThanOrEqual(2);
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
      },
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useAnalyticsFeedback>);
    renderPage();
    // The card still renders, with a friendly hint and an em-dash for the value.
    expect(screen.getAllByText('User satisfaction').length).toBeGreaterThan(0);
    expect(screen.getByText('Awaiting first rating')).toBeInTheDocument();
    expect(screen.queryByTestId('feedback-distribution-chart')).not.toBeInTheDocument();
  });
});
