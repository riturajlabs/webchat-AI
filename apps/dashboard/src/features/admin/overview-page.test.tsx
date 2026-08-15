import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AdminOverviewPage } from './overview-page';
import { useAdminOverview } from './hooks';
import type { AdminOverview } from './types';

vi.mock('./hooks', () => ({
  useAdminOverview: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/admin/overview'),
}));

const mockedUseAdminOverview = vi.mocked(useAdminOverview);

const OVERVIEW: AdminOverview = {
  stats: {
    tenants: { total: 3, active: 2, suspended: 1 },
    users: { total: 10, active: 8, suspended: 2 },
    usage: {
      conversations: 120,
      messages: 400,
      input_tokens: 50000,
      output_tokens: 20000,
      total_tokens: 70000,
    },
    crawl_jobs: { total: 6, active: 1, failed: 1, error_rate: 0.1667 },
  },
  counts: {
    users: 10,
    tenants: 3,
    websites: 4,
    widgets: 5,
    documents: 20,
    chat_sessions: 120,
    messages: 400,
    usage_records: 90,
    api_keys: 7,
    subscriptions: 2,
    audit_logs: 15,
    admin_audit_logs: 1,
  },
  active_subscriptions: 2,
  total_revenue_cents: 29000,
  currency: 'USD',
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <AdminOverviewPage />
    </QueryClientProvider>,
  );
}

function mockOverview(state: Partial<ReturnType<typeof useAdminOverview>> = {}) {
  mockedUseAdminOverview.mockReturnValue({
    data: OVERVIEW,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminOverview>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockOverview();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AdminOverviewPage', () => {
  it('renders the admin sub-navigation', () => {
    renderPage();
    expect(screen.getByRole('navigation', { name: 'Admin sections' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Tenants' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Revenue' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'System' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Audit' })).toBeInTheDocument();
  });

  it('shows platform KPI cards from the overview endpoint', () => {
    renderPage();
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
    expect(screen.getByText('2 active · 1 suspended')).toBeInTheDocument();
    expect(screen.getAllByText('10').length).toBeGreaterThan(0);
    expect(screen.getByText('8 active · 2 suspended')).toBeInTheDocument();
    expect(screen.getByText('$290.00')).toBeInTheDocument();
    expect(screen.getByText('70k')).toBeInTheDocument();
    expect(screen.getByText('Crawl failures')).toBeInTheDocument();
    expect(screen.getByText('16.7% error rate')).toBeInTheDocument();
  });

  it('shows collection counts from the overview payload', () => {
    renderPage();
    expect(screen.getByTestId('count-websites')).toHaveTextContent('4');
    expect(screen.getByTestId('count-admin_audit_logs')).toHaveTextContent('1');
  });

  it('shows a loading skeleton while stats are pending', () => {
    mockOverview({ isPending: true, data: undefined });
    renderPage();
    expect(screen.getByRole('status', { name: 'Loading stats' })).toBeInTheDocument();
  });

  it('shows an error state with retry for the overview', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockOverview({ isError: true, error: new Error('Failed to load stats.'), refetch });
    renderPage();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load stats.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });
});
