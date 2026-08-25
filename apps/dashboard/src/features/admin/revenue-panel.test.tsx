import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RevenuePanel } from './revenue-panel';
import { useAdminRevenue } from './hooks';
import type { AdminRevenueReport } from './types';

vi.mock('./hooks', () => ({
  useAdminRevenue: vi.fn(),
}));

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>();
  return {
    ...actual,
    ResponsiveContainer: () => <div />,
  };
});

const mockedUseAdminRevenue = vi.mocked(useAdminRevenue);

const REVENUE: AdminRevenueReport = {
  total_revenue_cents: 29000,
  paid_payments: 3,
  active_subscriptions: 2,
  currency: 'USD',
  periods: [
    { period: '2026-06', revenue_cents: 9000, payments: 1 },
    { period: '2026-07', revenue_cents: 20000, payments: 2 },
  ],
  recent_payments: [
    {
      id: 'sub-1',
      tenant_id: 'tenant-1',
      plan_id: 'pro',
      status: 'paid',
      payment_provider: 'stripe',
      payment_id: 'pi_123',
      start_date: '2026-07-01T00:00:00Z',
      end_date: '2026-08-01T00:00:00Z',
      amount_cents: 20000,
      currency: 'USD',
      created_at: '2026-07-01T00:00:00Z',
    },
  ],
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderPanel() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <RevenuePanel />
    </QueryClientProvider>,
  );
}

function mockRevenue(state: Partial<ReturnType<typeof useAdminRevenue>> = {}) {
  mockedUseAdminRevenue.mockReturnValue({
    data: REVENUE,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminRevenue>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRevenue();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RevenuePanel', () => {
  it('shows revenue summary cards', () => {
    renderPanel();
    expect(screen.getByText('$290.00')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('2 months')).toBeInTheDocument();
  });

  it('renders the monthly revenue chart', async () => {
    renderPanel();
    expect(await screen.findByTestId('revenue-chart')).toBeInTheDocument();
  });

  it('lists recent payments with provider and amount', () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: 'Recent payments' })).toBeInTheDocument();
    expect(screen.getByText('stripe')).toBeInTheDocument();
    expect(screen.getByText('$200.00')).toBeInTheDocument();
  });

  it('shows a loading skeleton while pending', () => {
    mockRevenue({ isPending: true, data: undefined });
    renderPanel();
    expect(screen.getByRole('status', { name: 'Loading revenue' })).toBeInTheDocument();
  });

  it('shows an error state with retry', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockRevenue({ isError: true, error: new Error('Failed to load revenue.'), refetch });
    renderPanel();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load revenue.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('shows an empty state when there are no periods', () => {
    mockRevenue({ data: { ...REVENUE, periods: [], recent_payments: [] } });
    renderPanel();
    expect(screen.getByText('No revenue yet')).toBeInTheDocument();
    expect(screen.getByText('No payments yet')).toBeInTheDocument();
  });
});
