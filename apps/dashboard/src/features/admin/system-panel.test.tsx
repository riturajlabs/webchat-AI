import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SystemPanel } from './system-panel';
import { useAdminSystemHealth } from './hooks';
import type { AdminSystemHealth } from './types';

vi.mock('./hooks', () => ({
  useAdminSystemHealth: vi.fn(),
}));

const mockedUseAdminSystemHealth = vi.mocked(useAdminSystemHealth);

const HEALTH: AdminSystemHealth = {
  status: 'degraded',
  checks: [
    { name: 'MongoDB', status: 'ok' },
    { name: 'Redis', status: 'degraded' },
  ],
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
  checked_at: '2026-08-15T10:00:00Z',
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderPanel() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <SystemPanel />
    </QueryClientProvider>,
  );
}

function mockHealth(state: Partial<ReturnType<typeof useAdminSystemHealth>> = {}) {
  mockedUseAdminSystemHealth.mockReturnValue({
    data: HEALTH,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminSystemHealth>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockHealth();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('SystemPanel', () => {
  it('shows the overall status and dependency probes', () => {
    renderPanel();
    expect(screen.getByText('Dependency probes')).toBeInTheDocument();
    expect(screen.getAllByText('Degraded').length).toBeGreaterThan(0);
    expect(screen.getByText('MongoDB')).toBeInTheDocument();
    expect(screen.getByText('Redis')).toBeInTheDocument();
  });

  it('shows collection counts', () => {
    renderPanel();
    expect(screen.getByTestId('count-tenants')).toHaveTextContent('3');
    expect(screen.getByTestId('count-messages')).toHaveTextContent('400');
    expect(screen.getByTestId('count-admin_audit_logs')).toHaveTextContent('1');
  });

  it('shows a loading skeleton while pending', () => {
    mockHealth({ isPending: true, data: undefined });
    renderPanel();
    expect(screen.getByRole('status', { name: 'Loading system health' })).toBeInTheDocument();
  });

  it('shows an error state with retry', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockHealth({ isError: true, error: new Error('Failed to load system health.'), refetch });
    renderPanel();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load system health.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });
});
