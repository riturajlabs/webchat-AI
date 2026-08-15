import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UsagePage } from './usage-page';
import { useUsage } from './hooks';
import type { Usage } from './types';

vi.mock('./hooks', () => ({
  useUsage: vi.fn(),
}));

const mockedUseUsage = vi.mocked(useUsage);

function makeUsage(overrides: Partial<Usage> = {}): Usage {
  return {
    plan: {
      id: 'free',
      name: 'Free',
      description: 'For personal projects and evaluation.',
      limits: {
        max_websites: 1,
        max_monthly_messages: 1_000,
        max_monthly_tokens: 100_000,
        max_documents: 10,
        max_crawl_pages: 500,
      },
    },
    usage: {
      messages_sent: 850,
      ai_responses: 800,
      tokens_used: 80_000,
      documents_created: 5,
      crawl_pages: 120,
      websites: 1,
      documents: 5,
    },
    limits: [
      { metric: 'messages_sent', used: 850, limit: 1_000, percent: 85 },
      { metric: 'websites', used: 1, limit: 1, percent: 100 },
      { metric: 'tokens_used', used: 80_000, limit: 100_000, percent: 80 },
      { metric: 'documents', used: 5, limit: 10, percent: 50 },
      { metric: 'crawl_pages', used: 120, limit: 500, percent: 24 },
    ],
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <UsagePage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('UsagePage', () => {
  it('renders the plan and usage cards', async () => {
    mockedUseUsage.mockReturnValue({
      data: makeUsage(),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    renderPage();

    await waitFor(() => expect(screen.getByText('Usage & Billing')).toBeInTheDocument());
    expect(screen.getByText('Messages used')).toBeInTheDocument();
    expect(screen.getByText('850')).toBeInTheDocument();
    expect(screen.getByText('Of 1,000 this month')).toBeInTheDocument();
    expect(screen.getByText('Tokens used')).toBeInTheDocument();
    expect(screen.getByText('80k')).toBeInTheDocument();
    expect(screen.getAllByText('Documents').length).toBeGreaterThan(0);
    expect(screen.getByText('Current plan')).toBeInTheDocument();
    expect(screen.getByText('Free')).toBeInTheDocument();
  });

  it('renders a progress bar per limited metric', async () => {
    mockedUseUsage.mockReturnValue({
      data: makeUsage(),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    renderPage();

    await waitFor(() => expect(screen.getByLabelText('Messages usage')).toBeInTheDocument());
    expect(screen.getByLabelText('Messages usage')).toHaveAttribute('aria-valuenow', '85');
    expect(screen.getByText(/850 \/ 1,000/)).toBeInTheDocument();
    expect(screen.getByText(/80,000 \/ 100,000/)).toBeInTheDocument();
  });

  it('warns in amber when a metric crosses 80%', async () => {
    mockedUseUsage.mockReturnValue({
      data: makeUsage(),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    renderPage();

    await waitFor(() => expect(screen.getAllByText(/near limit/).length).toBeGreaterThan(0));
    const messageBar = screen.getByLabelText('Messages usage').firstElementChild;
    expect(messageBar?.className).toContain('bg-amber-500');
  });

  it('renders unlimited metrics without a bar', async () => {
    const enterprise = makeUsage({
      plan: {
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
      },
      limits: [
        { metric: 'messages_sent', used: 5, limit: null, percent: null },
        { metric: 'websites', used: 3, limit: null, percent: null },
      ],
    });
    mockedUseUsage.mockReturnValue({
      data: enterprise,
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as never);

    renderPage();

    await waitFor(() => expect(screen.getAllByText('Unlimited').length).toBeGreaterThan(0));
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('shows an error state with a retry action', async () => {
    mockedUseUsage.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      error: new Error('boom'),
      refetch: vi.fn(),
    } as never);

    renderPage();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
