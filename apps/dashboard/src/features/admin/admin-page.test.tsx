import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AdminPage } from './admin-page';
import {
  useAdminAuditLogs,
  useAdminCrawlJobs,
  useAdminForceLogout,
  useAdminStats,
  useAdminSuspendUser,
  useAdminTenantDetail,
  useAdminTenants,
  useAdminUpdateTenant,
  useAdminUsers,
} from './hooks';
import type {
  AdminAuditLogListResponse,
  AdminCrawlJobListResponse,
  AdminStats,
  AdminTenantDetail,
  AdminTenantListResponse,
  AdminUserListResponse,
} from './types';

vi.mock('./hooks', () => ({
  useAdminStats: vi.fn(),
  useAdminTenants: vi.fn(),
  useAdminTenantDetail: vi.fn(),
  useAdminUpdateTenant: vi.fn(),
  useAdminUsers: vi.fn(),
  useAdminSuspendUser: vi.fn(),
  useAdminForceLogout: vi.fn(),
  useAdminCrawlJobs: vi.fn(),
  useAdminAuditLogs: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from 'sonner';

const mockedUseAdminStats = vi.mocked(useAdminStats);
const mockedUseAdminTenants = vi.mocked(useAdminTenants);
const mockedUseAdminTenantDetail = vi.mocked(useAdminTenantDetail);
const mockedUseAdminUpdateTenant = vi.mocked(useAdminUpdateTenant);
const mockedUseAdminUsers = vi.mocked(useAdminUsers);
const mockedUseAdminSuspendUser = vi.mocked(useAdminSuspendUser);
const mockedUseAdminForceLogout = vi.mocked(useAdminForceLogout);
const mockedUseAdminCrawlJobs = vi.mocked(useAdminCrawlJobs);
const mockedUseAdminAuditLogs = vi.mocked(useAdminAuditLogs);

const STATS: AdminStats = {
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
};

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

const USER_LIST: AdminUserListResponse = {
  items: [
    {
      id: 'user-1',
      name: 'Jane Doe',
      email: 'jane@acme.example',
      role: 'owner',
      status: 'active',
      email_verified: true,
      tenant_id: 'tenant-1',
      last_login: '2026-08-05T00:00:00Z',
      created_at: '2026-08-01T00:00:00Z',
    },
    {
      id: 'user-2',
      name: 'John Roe',
      email: 'john@acme.example',
      role: 'admin',
      status: 'suspended',
      email_verified: false,
      tenant_id: 'tenant-1',
      last_login: null,
      created_at: '2026-08-02T00:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  per_page: 20,
};

const CRAWL_LIST: AdminCrawlJobListResponse = {
  items: [
    {
      id: 'job-1',
      tenant_id: 'tenant-1',
      website_id: 'site-1',
      status: 'running',
      pages_total: 10,
      pages_completed: 4,
      error_message: null,
      created_at: '2026-08-10T00:00:00Z',
      updated_at: '2026-08-10T00:00:00Z',
    },
  ],
  total: 1,
  page: 1,
  per_page: 20,
};

const AUDIT_LIST: AdminAuditLogListResponse = {
  items: [
    {
      id: 'log-1',
      tenant_id: 'tenant-1',
      user_id: 'user-1',
      action: 'LOGIN',
      ip_address: '127.0.0.1',
      user_agent: 'Mozilla/5.0',
      created_at: '2026-08-10T12:00:00Z',
    },
  ],
  total: 1,
  page: 1,
  per_page: 20,
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <AdminPage />
    </QueryClientProvider>,
  );
}

function mockStats(state: Partial<ReturnType<typeof useAdminStats>> = {}) {
  mockedUseAdminStats.mockReturnValue({
    data: STATS,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminStats>);
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

function mockTenantDetail(state: Partial<ReturnType<typeof useAdminTenantDetail>> = {}) {
  mockedUseAdminTenantDetail.mockReturnValue({
    data: TENANT_DETAIL,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminTenantDetail>);
}

function mockUsers(state: Partial<ReturnType<typeof useAdminUsers>> = {}) {
  mockedUseAdminUsers.mockReturnValue({
    data: USER_LIST,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminUsers>);
}

function mockCrawlJobs(state: Partial<ReturnType<typeof useAdminCrawlJobs>> = {}) {
  mockedUseAdminCrawlJobs.mockReturnValue({
    data: CRAWL_LIST,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminCrawlJobs>);
}

function mockAuditLogs(state: Partial<ReturnType<typeof useAdminAuditLogs>> = {}) {
  mockedUseAdminAuditLogs.mockReturnValue({
    data: AUDIT_LIST,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn().mockResolvedValue(undefined),
    ...state,
  } as unknown as ReturnType<typeof useAdminAuditLogs>);
}

function mockMutations() {
  mockedUseAdminUpdateTenant.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(TENANT_LIST.items[0]),
    isPending: false,
  } as unknown as ReturnType<typeof useAdminUpdateTenant>);
  mockedUseAdminSuspendUser.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(USER_LIST.items[1]),
    isPending: false,
  } as unknown as ReturnType<typeof useAdminSuspendUser>);
  mockedUseAdminForceLogout.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(USER_LIST.items[0]),
    isPending: false,
  } as unknown as ReturnType<typeof useAdminForceLogout>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockStats();
  mockTenants();
  mockTenantDetail();
  mockUsers();
  mockCrawlJobs();
  mockAuditLogs();
  mockMutations();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('AdminPage', () => {
  it('shows platform KPI cards from the stats endpoint', () => {
    renderPage();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2 active · 1 suspended')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('8 active · 2 suspended')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('Crawl failures')).toBeInTheDocument();
    expect(screen.getByText('16.7% error rate')).toBeInTheDocument();
  });

  it('shows a loading skeleton while stats are pending', () => {
    mockStats({ isPending: true, data: undefined });
    renderPage();
    expect(screen.getByRole('status', { name: 'Loading stats' })).toBeInTheDocument();
  });

  it('shows an error state with retry for stats', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockStats({ isError: true, error: new Error('Failed to load stats.'), refetch });
    renderPage();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load stats.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('renders the tenant table by default and switches tabs', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'Tenants' })).toBeInTheDocument();
    expect(screen.getByText('Acme Inc')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Users' }));
    expect(screen.getByRole('heading', { name: 'Users' })).toBeInTheDocument();
    expect(screen.getByText('jane@acme.example')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Crawl queue' }));
    expect(screen.getByRole('heading', { name: 'Crawl queue' })).toBeInTheDocument();
    expect(screen.getByText('tenant-1')).toBeInTheDocument();
    expect(screen.getByText('4 / 10 pages')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Audit log' }));
    expect(screen.getByRole('heading', { name: 'Audit log' })).toBeInTheDocument();
    expect(screen.getByText('LOGIN')).toBeInTheDocument();
  });

  it('opens tenant details and shows usage aggregates', () => {
    renderPage();
    fireEvent.click(screen.getAllByRole('button', { name: /Details/ })[0]);
    const dialog = screen.getByRole('dialog', { name: 'Acme Inc' });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText('4')).toBeInTheDocument();
    expect(within(dialog).getByText('6')).toBeInTheDocument();
    expect(within(dialog).getByText('100')).toBeInTheDocument();
    expect(within(dialog).getByText('300')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog', { name: 'Acme Inc' })).not.toBeInTheDocument();
  });

  it('suspends a tenant after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(TENANT_LIST.items[0]);
    mockedUseAdminUpdateTenant.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAdminUpdateTenant>);
    renderPage();

    const row = screen.getByText('Acme Inc').closest('tr');
    expect(row).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Suspend' }));

    expect(screen.getByText('Suspend Acme Inc?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    expect(await mutateAsync).toHaveBeenCalledWith({
      tenantId: 'tenant-1',
      body: { status: 'suspended' },
    });
    expect(toast.success).toHaveBeenCalledWith('Acme Inc suspended');
  });

  it('activates a suspended tenant after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(TENANT_LIST.items[1]);
    mockedUseAdminUpdateTenant.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAdminUpdateTenant>);
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Activate' }));

    expect(screen.getByText('Activate Globex?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    expect(await mutateAsync).toHaveBeenCalledWith({
      tenantId: 'tenant-2',
      body: { status: 'active' },
    });
    expect(toast.success).toHaveBeenCalledWith('Globex activated');
  });

  it('shows a tenant error state when the list fails', () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    mockTenants({ isError: true, error: new Error('Failed to load tenants.'), refetch });
    renderPage();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load tenants.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalled();
  });

  it('filters users by status', () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Users' }));
    fireEvent.change(screen.getByLabelText('Filter by status'), {
      target: { value: 'suspended' },
    });
    const lastCall = mockedUseAdminUsers.mock.calls[mockedUseAdminUsers.mock.calls.length - 1];
    expect(lastCall[3]).toBe('suspended');
    expect(lastCall[0]).toBe(1);
  });

  it('suspends a user after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(USER_LIST.items[1]);
    mockedUseAdminSuspendUser.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAdminSuspendUser>);
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Users' }));

    const janeRow = screen.getByText('Jane Doe').closest('tr');
    expect(janeRow).not.toBeNull();
    fireEvent.click(within(janeRow as HTMLElement).getByRole('button', { name: /Suspend/ }));

    expect(screen.getByText('Suspend Jane Doe?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    expect(await mutateAsync).toHaveBeenCalledWith({
      tenantId: 'tenant-1',
      userId: 'user-1',
    });
    expect(toast.success).toHaveBeenCalledWith('Jane Doe suspended');
  });

  it('forces logout for a user after confirmation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(USER_LIST.items[0]);
    mockedUseAdminForceLogout.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useAdminForceLogout>);
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Users' }));

    const janeRow = screen.getByText('Jane Doe').closest('tr');
    expect(janeRow).not.toBeNull();
    fireEvent.click(within(janeRow as HTMLElement).getByRole('button', { name: /Force logout/ }));

    expect(screen.getByText('Force logout Jane Doe?')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    expect(await mutateAsync).toHaveBeenCalledWith({
      tenantId: 'tenant-1',
      userId: 'user-1',
    });
    expect(toast.success).toHaveBeenCalledWith('Jane Doe signed out of all devices');
  });

  it('disables suspend for already-suspended users', () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Users' }));

    const row = screen.getByText('John Roe').closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByRole('button', { name: /Suspend/ })).toBeDisabled();
  });

  it('paginates crawl jobs', () => {
    mockCrawlJobs({ data: { ...CRAWL_LIST, total: 40 } });
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Crawl queue' }));
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    const lastCall =
      mockedUseAdminCrawlJobs.mock.calls[mockedUseAdminCrawlJobs.mock.calls.length - 1];
    expect(lastCall[0]).toBe(2);
  });

  it('filters audit log by action', () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'Audit log' }));
    const input = screen.getByLabelText('Filter by action');
    fireEvent.change(input, { target: { value: 'register' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    const lastCall =
      mockedUseAdminAuditLogs.mock.calls[mockedUseAdminAuditLogs.mock.calls.length - 1];
    expect(lastCall[2]).toBe('REGISTER');
    expect(lastCall[0]).toBe(1);
  });

  it('shows an empty state for tenants when none match filters', () => {
    vi.useFakeTimers();
    mockTenants({ data: { items: [], total: 0, page: 1, per_page: 20 } });
    renderPage();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search tenants' }), {
      target: { value: 'nothing' },
    });
    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(screen.getByText('No matching tenants')).toBeInTheDocument();
  });
});
