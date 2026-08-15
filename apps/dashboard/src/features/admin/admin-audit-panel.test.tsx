import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AdminAuditPanel } from './admin-audit-panel';
import { useAdminAdminAuditLogs } from './hooks';
import type { AdminAdminAuditLogListResponse } from './types';

vi.mock('./hooks', () => ({
  useAdminAdminAuditLogs: vi.fn(),
}));

const mockedUseAdminAdminAuditLogs = vi.mocked(useAdminAdminAuditLogs);

const LOG_LIST: AdminAdminAuditLogListResponse = {
  items: [
    {
      id: 'log-1',
      actor_user_id: 'sa-1',
      action: 'TENANT_SUSPENDED',
      tenant_id: 'tenant-1',
      user_id: null,
      plan_id: null,
      ip_address: '127.0.0.1',
      user_agent: 'Mozilla/5.0',
      created_at: '2026-08-15T09:00:00Z',
    },
    {
      id: 'log-2',
      actor_user_id: 'sa-1',
      action: 'TENANT_PLAN_CHANGED',
      tenant_id: 'tenant-2',
      user_id: null,
      plan_id: 'enterprise',
      ip_address: '127.0.0.1',
      user_agent: null,
      created_at: '2026-08-15T08:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  per_page: 20,
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderPanel() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <AdminAuditPanel />
    </QueryClientProvider>,
  );
}

function mockLogs(state: Partial<ReturnType<typeof useAdminAdminAuditLogs>> = {}) {
  mockedUseAdminAdminAuditLogs.mockReturnValue({
    data: LOG_LIST,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminAdminAuditLogs>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLogs();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AdminAuditPanel', () => {
  it('lists admin actions with actor and plan context', () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: 'Admin audit trail' })).toBeInTheDocument();
    expect(screen.getByText('TENANT_SUSPENDED')).toBeInTheDocument();
    expect(screen.getByText('TENANT_PLAN_CHANGED')).toBeInTheDocument();
    expect(screen.getByText('enterprise')).toBeInTheDocument();
    expect(screen.getAllByText('sa-1').length).toBeGreaterThan(0);
  });

  it('applies action and tenant filters', () => {
    renderPanel();
    const actionInput = screen.getByLabelText('Filter by action');
    fireEvent.change(actionInput, { target: { value: 'tenant_suspended' } });
    const tenantInput = screen.getByLabelText('Filter by tenant');
    fireEvent.change(tenantInput, { target: { value: 'tenant-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));

    const lastCall =
      mockedUseAdminAdminAuditLogs.mock.calls[mockedUseAdminAdminAuditLogs.mock.calls.length - 1];
    expect(lastCall[2]).toBe('TENANT_SUSPENDED');
    expect(lastCall[3]).toBe('tenant-1');
    expect(lastCall[0]).toBe(1);
  });

  it('clears filters', () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText('Filter by action'), {
      target: { value: 'tenant_suspended' },
    });
    fireEvent.change(screen.getByLabelText('Filter by tenant'), {
      target: { value: 'tenant-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));

    const lastCall =
      mockedUseAdminAdminAuditLogs.mock.calls[mockedUseAdminAdminAuditLogs.mock.calls.length - 1];
    expect(lastCall[2]).toBe('');
    expect(lastCall[3]).toBe('');
  });

  it('shows an empty state when no events match', () => {
    mockLogs({ data: { items: [], total: 0, page: 1, per_page: 20 } });
    renderPanel();
    fireEvent.change(screen.getByLabelText('Filter by action'), {
      target: { value: 'FORCE_LOGOUT' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Filter' }));
    expect(screen.getByText('No matching admin actions')).toBeInTheDocument();
  });

  it('paginates events', () => {
    mockLogs({ data: { ...LOG_LIST, total: 40 } });
    renderPanel();
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    const lastCall =
      mockedUseAdminAdminAuditLogs.mock.calls[mockedUseAdminAdminAuditLogs.mock.calls.length - 1];
    expect(lastCall[0]).toBe(2);
  });

  it('shows an error state with retry', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockLogs({ isError: true, error: new Error('Failed to load admin audit log.'), refetch });
    renderPanel();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load admin audit log.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });
});
