import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TenantPanel } from './tenant-panel';
import {
  useAdminActivateTenant,
  useAdminChangeTenantPlan,
  useAdminSuspendTenant,
  useAdminTenantDetail,
  useAdminTenants,
} from './hooks';
import type { AdminTenantDetail, AdminTenantListResponse } from './types';

vi.mock('./hooks', () => ({
  useAdminTenants: vi.fn(),
  useAdminTenantDetail: vi.fn(),
  useAdminSuspendTenant: vi.fn(),
  useAdminActivateTenant: vi.fn(),
  useAdminChangeTenantPlan: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from 'sonner';

const mockedUseAdminTenants = vi.mocked(useAdminTenants);
const mockedUseAdminTenantDetail = vi.mocked(useAdminTenantDetail);
const mockedUseAdminSuspendTenant = vi.mocked(useAdminSuspendTenant);
const mockedUseAdminActivateTenant = vi.mocked(useAdminActivateTenant);
const mockedUseAdminChangeTenantPlan = vi.mocked(useAdminChangeTenantPlan);

const TENANT_LIST: AdminTenantListResponse = {
  items: [
    {
      id: 'tenant-1',
      company_name: 'Acme Inc',
      plan: 'pro',
      status: 'active',
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    },
    {
      id: 'tenant-2',
      company_name: 'Globex',
      plan: 'free',
      status: 'suspended',
      created_at: '2026-07-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  per_page: 20,
};

const TENANT_DETAIL: AdminTenantDetail = {
  ...TENANT_LIST.items[0],
  website_count: 4,
  user_count: 6,
  active_crawl_jobs: 1,
  usage: { conversations: 100, messages: 300, input_tokens: 40000, output_tokens: 15000 },
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderPanel() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <TenantPanel />
    </QueryClientProvider>,
  );
}

function mockTenants(state: Partial<ReturnType<typeof useAdminTenants>> = {}) {
  mockedUseAdminTenants.mockReturnValue({
    data: TENANT_LIST,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminTenants>);
}

function mockMutations() {
  mockedUseAdminSuspendTenant.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(TENANT_LIST.items[0]),
    isPending: false,
  } as unknown as ReturnType<typeof useAdminSuspendTenant>);
  mockedUseAdminActivateTenant.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(TENANT_LIST.items[1]),
    isPending: false,
  } as unknown as ReturnType<typeof useAdminActivateTenant>);
  mockedUseAdminChangeTenantPlan.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(TENANT_LIST.items[0]),
    isPending: false,
  } as unknown as ReturnType<typeof useAdminChangeTenantPlan>);
  mockedUseAdminTenantDetail.mockReturnValue({
    data: TENANT_DETAIL,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAdminTenantDetail>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockTenants();
  mockMutations();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('TenantPanel', () => {
  it('lists tenants with plan, status and created date', () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: 'Tenants' })).toBeInTheDocument();
    expect(screen.getByText('Acme Inc')).toBeInTheDocument();
    expect(screen.getByText('Globex')).toBeInTheDocument();
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Suspended').length).toBeGreaterThan(0);
  });

  it('passes the plan filter to the tenants query', () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText('Filter by plan'), {
      target: { value: 'enterprise' },
    });
    const lastCall = mockedUseAdminTenants.mock.calls[mockedUseAdminTenants.mock.calls.length - 1];
    expect(lastCall[3]).toBe('enterprise');
    expect(lastCall[4]).toBe('');
    expect(lastCall[0]).toBe(1);
  });

  it('passes the status filter to the tenants query', () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText('Filter by status'), {
      target: { value: 'suspended' },
    });
    const lastCall = mockedUseAdminTenants.mock.calls[mockedUseAdminTenants.mock.calls.length - 1];
    expect(lastCall[4]).toBe('suspended');
    expect(lastCall[0]).toBe(1);
  });

  it('debounces the search input before querying', () => {
    vi.useFakeTimers();
    renderPanel();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search tenants' }), {
      target: { value: 'acme' },
    });
    const before = mockedUseAdminTenants.mock.calls.length;
    act(() => {
      vi.advanceTimersByTime(350);
    });
    const lastCall = mockedUseAdminTenants.mock.calls[mockedUseAdminTenants.mock.calls.length - 1];
    expect(mockedUseAdminTenants.mock.calls.length).toBeGreaterThan(before);
    expect(lastCall[2]).toBe('acme');
  });

  it('shows an empty state when no tenants match filters', () => {
    vi.useFakeTimers();
    mockTenants({ data: { items: [], total: 0, page: 1, per_page: 20 } });
    renderPanel();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search tenants' }), {
      target: { value: 'nothing' },
    });
    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(screen.getByText('No matching tenants')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  });

  it('suspends an active tenant after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(TENANT_LIST.items[0]);
    mockedUseAdminSuspendTenant.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAdminSuspendTenant>);
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Suspend' }));

    expect(screen.getByText('Suspend Acme Inc?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    expect(await mutateAsync).toHaveBeenCalledWith({ tenantId: 'tenant-1' });
    expect(toast.success).toHaveBeenCalledWith('Acme Inc suspended');
  });

  it('activates a suspended tenant after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(TENANT_LIST.items[1]);
    mockedUseAdminActivateTenant.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAdminActivateTenant>);
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Activate' }));

    expect(screen.getByText('Activate Globex?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    expect(await mutateAsync).toHaveBeenCalledWith({ tenantId: 'tenant-2' });
    expect(toast.success).toHaveBeenCalledWith('Globex activated');
  });

  it('opens tenant details and allows changing the plan', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(TENANT_LIST.items[0]);
    mockedUseAdminChangeTenantPlan.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAdminChangeTenantPlan>);
    renderPanel();

    fireEvent.click(screen.getAllByRole('button', { name: /Details/ })[0]);
    const dialog = screen.getByRole('dialog', { name: 'Acme Inc' });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText('6')).toBeInTheDocument();
    expect(within(dialog).getByText('100')).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText('Plan'), {
      target: { value: 'enterprise' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save plan' }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ tenantId: 'tenant-1', plan: 'enterprise' }),
    );
    expect(toast.success).toHaveBeenCalledWith('Plan changed to enterprise');
  });

  it('shows a tenant error state when the list fails', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockTenants({ isError: true, error: new Error('Failed to load tenants.'), refetch });
    renderPanel();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load tenants.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('paginates tenants', () => {
    mockTenants({ data: { ...TENANT_LIST, total: 40 } });
    renderPanel();
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    const lastCall = mockedUseAdminTenants.mock.calls[mockedUseAdminTenants.mock.calls.length - 1];
    expect(lastCall[0]).toBe(2);
  });

  // --- Accessibility tests ---

  it('closes the confirm dialog on Escape key', () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Suspend' }));
    expect(screen.getByText('Suspend Acme Inc?')).toBeInTheDocument();

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(screen.queryByText('Suspend Acme Inc?')).not.toBeInTheDocument();
  });

  it('closes the tenant detail dialog on Escape key', () => {
    renderPanel();

    fireEvent.click(screen.getAllByRole('button', { name: /Details/ })[0]);
    expect(screen.getByRole('dialog', { name: 'Acme Inc' })).toBeInTheDocument();

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(screen.queryByRole('dialog', { name: 'Acme Inc' })).not.toBeInTheDocument();
  });

  it('sets inert on background when tenant detail dialog is open', () => {
    renderPanel();

    fireEvent.click(screen.getAllByRole('button', { name: /Details/ })[0]);

    const inertElements = document.querySelectorAll('[inert]');
    expect(inertElements.length).toBeGreaterThan(0);
  });
});
