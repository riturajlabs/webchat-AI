import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { usePlans, useUsage } from '@/features/usage/hooks';

import { BillingPage } from './billing-page';
import { useCreateCheckout, useSubscriptionReport } from './hooks';
import type { PaymentOut, SubscriptionOut } from './types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('./hooks', () => ({
  useSubscriptionReport: vi.fn(),
  useCreateCheckout: vi.fn(),
}));

vi.mock('@/features/usage/hooks', () => ({
  useUsage: vi.fn(),
  usePlans: vi.fn(),
}));

const mockedUseSubscriptionReport = vi.mocked(useSubscriptionReport);
const mockedUseCreateCheckout = vi.mocked(useCreateCheckout);
const mockedUseUsage = vi.mocked(useUsage);
const mockedUsePlans = vi.mocked(usePlans);

const SUBSCRIPTION: SubscriptionOut = {
  id: 'sub-1',
  plan_id: 'pro',
  plan_name: 'Pro',
  status: 'active',
  payment_provider: 'stripe',
  payment_id: 'cs_test_1',
  start_date: '2026-08-01T00:00:00Z',
  end_date: '2026-08-31T00:00:00Z',
  created_at: '2026-08-01T00:00:00Z',
};

const PAYMENTS: PaymentOut[] = [
  {
    id: 'sub-1',
    plan_id: 'pro',
    plan_name: 'Pro',
    status: 'active',
    amount_cents: 2900,
    currency: 'USD',
    payment_provider: 'stripe',
    payment_id: 'cs_test_1',
    created_at: '2026-08-01T00:00:00Z',
  },
];

const PLANS = [
  {
    id: 'free',
    name: 'Free',
    description: 'For personal projects and evaluation.',
    limits: {
      max_websites: 1,
      max_monthly_messages: 1000,
      max_monthly_tokens: 100000,
      max_documents: 10,
      max_crawl_pages: 500,
    },
    price_cents: 0,
    currency: 'USD',
  },
  {
    id: 'pro',
    name: 'Pro',
    description: 'For growing teams with higher usage.',
    limits: {
      max_websites: 5,
      max_monthly_messages: 50000,
      max_monthly_tokens: 2000000,
      max_documents: 100,
      max_crawl_pages: 5000,
    },
    price_cents: 2900,
    currency: 'USD',
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    description: 'Custom limits for high-volume deployments.',
    limits: {
      max_websites: null,
      max_monthly_messages: null,
      max_monthly_tokens: null,
      max_documents: null,
      max_crawl_pages: null,
    },
    price_cents: null,
    currency: 'USD',
  },
];

function mockReport(state: Partial<ReturnType<typeof useSubscriptionReport>> = {}) {
  mockedUseSubscriptionReport.mockReturnValue({
    data: { subscription: SUBSCRIPTION, payments: PAYMENTS },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useSubscriptionReport>);
}

function mockUsage() {
  mockedUseUsage.mockReturnValue({
    data: {
      plan: PLANS[0],
      usage: {
        messages_sent: 850,
        ai_responses: 800,
        tokens_used: 80000,
        documents_created: 5,
        crawl_pages: 120,
        websites: 1,
        documents: 5,
      },
      limits: [],
    },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useUsage>);
}

function mockPlans() {
  mockedUsePlans.mockReturnValue({
    data: PLANS,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof usePlans>);
}

function mockCheckout() {
  const mutate = vi.fn();
  mockedUseCreateCheckout.mockReturnValue({
    mutate,
  } as unknown as ReturnType<typeof useCreateCheckout>);
  return mutate;
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BillingPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('BillingPage', () => {
  it('renders the current plan with an active status badge', async () => {
    mockReport();
    mockUsage();
    mockPlans();
    mockCheckout();

    renderPage();

    await waitFor(() => expect(screen.getAllByText('Current plan').length).toBeGreaterThan(0));
    expect(screen.getAllByText('Pro').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0);
    expect(screen.getByText(/Paid via stripe/)).toBeInTheDocument();
  });

  it('renders the monthly usage summary', async () => {
    mockReport();
    mockUsage();
    mockPlans();
    mockCheckout();

    renderPage();

    await waitFor(() => expect(screen.getByText('Usage this month')).toBeInTheDocument());
    expect(screen.getByText('Messages')).toBeInTheDocument();
    expect(screen.getByText('850')).toBeInTheDocument();
    expect(screen.getByText('Tokens')).toBeInTheDocument();
    expect(screen.getByText('80k')).toBeInTheDocument();
  });

  it('lists plans with prices and starts a checkout on upgrade', async () => {
    mockReport({
      data: { subscription: { ...SUBSCRIPTION, plan_id: 'free', plan_name: 'Free' }, payments: [] },
    });
    mockUsage();
    mockPlans();
    const mutate = mockCheckout();

    renderPage();

    await waitFor(() => expect(screen.getAllByText('Upgrade').length).toBeGreaterThan(0));
    const upgradeButton = screen.getAllByRole('button', { name: 'Upgrade' })[0];
    fireEvent.click(upgradeButton);

    expect(mutate).toHaveBeenCalledWith(
      {
        plan_id: 'pro',
        success_url: expect.stringMatching(/\/billing\?status=success$/),
        cancel_url: expect.stringMatching(/\/billing\?status=cancelled$/),
      },
      expect.objectContaining({ onError: expect.any(Function) }),
    );
  });

  it('marks the active plan as current without an upgrade CTA', async () => {
    mockReport();
    mockUsage();
    mockPlans();
    mockCheckout();

    renderPage();

    await waitFor(() => expect(screen.getByRole('link', { name: 'Manage' })).toBeInTheDocument());
    expect(screen.queryAllByRole('button', { name: 'Upgrade' })).toHaveLength(0);
    expect(screen.getAllByText(/Unlimited/).length).toBeGreaterThan(0);
  });

  it('shows non-purchasable plans without an upgrade button', async () => {
    mockReport({ data: { subscription: null, payments: [] } });
    mockUsage();
    mockPlans();
    mockCheckout();

    renderPage();

    await waitFor(() => expect(screen.getAllByText('Upgrade').length).toBeGreaterThan(0));
    expect(screen.getByText('Trial plan')).toBeInTheDocument();
    expect(screen.getByText('Contact sales')).toBeInTheDocument();
  });

  it('renders payment history in a table', async () => {
    mockReport();
    mockUsage();
    mockPlans();
    mockCheckout();

    renderPage();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Billing history' })).toBeInTheDocument(),
    );
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getAllByText('Pro').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$29.00').length).toBeGreaterThan(0);
  });

  it('shows an empty state when there are no payments', async () => {
    mockReport({ data: { subscription: null, payments: [] } });
    mockUsage();
    mockPlans();
    mockCheckout();

    renderPage();

    await waitFor(() => expect(screen.getByText('No payments yet')).toBeInTheDocument());
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows an error state with a retry action', async () => {
    mockReport({
      data: undefined,
      isPending: false,
      isError: true,
      error: new Error('boom'),
    });
    mockUsage();
    mockPlans();
    mockCheckout();

    renderPage();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
