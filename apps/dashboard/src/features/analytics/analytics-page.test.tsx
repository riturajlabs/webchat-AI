import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AnalyticsPage } from './analytics-page';
import {
  useAnalyticsPerformance,
  useAnalyticsSummary,
  useAnalyticsTimeseries,
  useAnalyticsTopWebsites,
} from './hooks';
import type { AnalyticsSummary, ResponseMetrics, TimeseriesPoint, TopWebsite } from './types';

vi.mock('@/features/websites/hooks', () => ({
  useWebsites: vi.fn(),
}));

vi.mock('./hooks', () => ({
  useAnalyticsSummary: vi.fn(),
  useAnalyticsTimeseries: vi.fn(),
  useAnalyticsTopWebsites: vi.fn(),
  useAnalyticsPerformance: vi.fn(),
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
  return {
    ResponsiveContainer: MockResponsiveContainer,
    ComposedChart: (props: Record<string, unknown>) => (
      <Chart {...props} data-testid="activity-chart" />
    ),
    AreaChart: (props: Record<string, unknown>) => <Chart {...props} data-testid="token-chart" />,
    BarChart: (props: Record<string, unknown>) => (
      <Chart {...props} data-testid="top-websites-chart" />
    ),
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
    expect(screen.getByText('AI responses')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('Estimated cost')).toBeInTheDocument();
    expect(screen.getByText('$0.0105')).toBeInTheDocument();
    expect(screen.getByText('Avg response time')).toBeInTheDocument();
    expect(screen.getAllByText('1.25s').length).toBeGreaterThan(0);
  });

  it('renders the charts once mounted', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('activity-chart')).toBeInTheDocument();
    });
    expect(screen.getByTestId('token-chart')).toBeInTheDocument();
    expect(screen.getByTestId('top-websites-chart')).toBeInTheDocument();
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
});
