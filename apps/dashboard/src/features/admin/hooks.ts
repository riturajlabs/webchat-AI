/**
 * React Query hooks for the admin feature (Phase 12.5 + Phase 15, ADR-006).
 * Every endpoint is guarded by `role=super_admin` on the backend; these hooks
 * only run for super-admin principals (see AdminGuard).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

import type {
  AdminAdminAuditLog,
  AdminAdminAuditLogListResponse,
  AdminAuditLog,
  AdminAuditLogListResponse,
  AdminCrawlJob,
  AdminCrawlJobListResponse,
  AdminOverview,
  AdminRevenueReport,
  AdminStats,
  AdminSystemHealth,
  AdminTenant,
  AdminTenantDetail,
  AdminTenantListResponse,
  AdminUser,
  AdminUserListResponse,
} from './types';

export const adminKeys = {
  all: ['admin'] as const,
  stats: ['admin', 'stats'] as const,
  overview: ['admin', 'overview'] as const,
  revenue: ['admin', 'revenue'] as const,
  systemHealth: ['admin', 'system-health'] as const,
  tenants: (page: number, perPage: number, search: string, plan: string, status: string) =>
    ['admin', 'tenants', { page, perPage, search, plan, status }] as const,
  tenantDetail: (tenantId: string) => ['admin', 'tenants', tenantId] as const,
  users: (page: number, perPage: number, search: string, status: string) =>
    ['admin', 'users', { page, perPage, search, status }] as const,
  crawlJobs: (page: number, perPage: number, status: string) =>
    ['admin', 'crawl-jobs', { page, perPage, status }] as const,
  auditLogs: (page: number, perPage: number, action: string) =>
    ['admin', 'audit-logs', { page, perPage, action }] as const,
  adminAuditLogs: (page: number, perPage: number, action: string, tenantId: string) =>
    ['admin', 'audit', { page, perPage, action, tenantId }] as const,
};

function queryParams(extra: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(extra)) {
    if (value) {
      params.set(key, value);
    }
  }
  return params.toString();
}

export function useAdminOverview() {
  return useQuery({
    queryKey: adminKeys.overview,
    queryFn: () => api.get<AdminOverview>('/api/admin/overview'),
  });
}

export function useAdminStats() {
  return useQuery({
    queryKey: adminKeys.stats,
    queryFn: () => api.get<AdminStats>('/api/admin/stats'),
  });
}

export function useAdminRevenue() {
  return useQuery({
    queryKey: adminKeys.revenue,
    queryFn: () => api.get<AdminRevenueReport>('/api/admin/revenue'),
  });
}

export function useAdminSystemHealth() {
  return useQuery({
    queryKey: adminKeys.systemHealth,
    queryFn: () => api.get<AdminSystemHealth>('/api/admin/system-health'),
    refetchInterval: 30_000,
  });
}

export function useAdminTenants(
  page: number,
  perPage: number,
  search: string,
  plan: string,
  status: string,
) {
  const query = queryParams({
    page: String(page),
    per_page: String(perPage),
    search,
    plan,
    status,
  });
  return useQuery({
    queryKey: adminKeys.tenants(page, perPage, search, plan, status),
    queryFn: () => api.get<AdminTenantListResponse>(`/api/admin/tenants?${query}`),
  });
}

export function useAdminTenantDetail(tenantId: string | null) {
  return useQuery({
    queryKey: adminKeys.tenantDetail(tenantId ?? ''),
    queryFn: () => api.get<AdminTenantDetail>(`/api/admin/tenants/${tenantId}`),
    enabled: tenantId !== null,
  });
}

export function useAdminSuspendTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId }: { tenantId: string }) =>
      api.post<AdminTenant>(`/api/admin/tenants/${tenantId}/suspend`),
    onSuccess: (data) => {
      queryClient.setQueryData<AdminTenantDetail>(adminKeys.tenantDetail(data.id), (current) =>
        current ? { ...current, status: data.status, plan: data.plan } : current,
      );
      void queryClient.invalidateQueries({ queryKey: adminKeys.stats });
      void queryClient.invalidateQueries({ queryKey: adminKeys.overview });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'tenants'] });
    },
  });
}

export function useAdminActivateTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId }: { tenantId: string }) =>
      api.post<AdminTenant>(`/api/admin/tenants/${tenantId}/activate`),
    onSuccess: (data) => {
      queryClient.setQueryData<AdminTenantDetail>(adminKeys.tenantDetail(data.id), (current) =>
        current ? { ...current, status: data.status, plan: data.plan } : current,
      );
      void queryClient.invalidateQueries({ queryKey: adminKeys.stats });
      void queryClient.invalidateQueries({ queryKey: adminKeys.overview });
      void queryClient.invalidateQueries({ queryKey: ['admin', 'tenants'] });
    },
  });
}

export function useAdminChangeTenantPlan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, plan }: { tenantId: string; plan: string }) =>
      api.post<AdminTenant>(`/api/admin/tenants/${tenantId}/plan`, { plan }),
    onSuccess: (data) => {
      queryClient.setQueryData<AdminTenantDetail>(adminKeys.tenantDetail(data.id), (current) =>
        current ? { ...current, status: data.status, plan: data.plan } : current,
      );
      void queryClient.invalidateQueries({ queryKey: ['admin', 'tenants'] });
    },
  });
}

export function useAdminUsers(page: number, perPage: number, search: string, status: string) {
  const query = queryParams({ page: String(page), per_page: String(perPage), search, status });
  return useQuery({
    queryKey: adminKeys.users(page, perPage, search, status),
    queryFn: () => api.get<AdminUserListResponse>(`/api/admin/users?${query}`),
  });
}

export function useAdminSuspendUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, userId }: { tenantId: string; userId: string }) =>
      api.post<AdminUser>(`/api/admin/tenants/${tenantId}/users/${userId}/suspend`),
    onSuccess: (data) => {
      queryClient.setQueryData<AdminUser>(['admin', 'user', data.id], data);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
      void queryClient.invalidateQueries({ queryKey: adminKeys.stats });
    },
  });
}

export function useAdminForceLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, userId }: { tenantId: string; userId: string }) =>
      api.post<AdminUser>(`/api/admin/tenants/${tenantId}/users/${userId}/force-logout`),
    onSuccess: (data) => {
      queryClient.setQueryData<AdminUser>(['admin', 'user', data.id], data);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
  });
}

export function useAdminCrawlJobs(page: number, perPage: number, status: string) {
  const query = queryParams({ page: String(page), per_page: String(perPage), status });
  return useQuery({
    queryKey: adminKeys.crawlJobs(page, perPage, status),
    queryFn: () => api.get<AdminCrawlJobListResponse>(`/api/admin/crawl-jobs?${query}`),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) =>
        ['pending', 'running', 'processing'].includes(job.status),
      )
        ? 5000
        : false,
  });
}

export function useAdminAuditLogs(page: number, perPage: number, action: string) {
  const query = queryParams({ page: String(page), per_page: String(perPage), action });
  return useQuery({
    queryKey: adminKeys.auditLogs(page, perPage, action),
    queryFn: () => api.get<AdminAuditLogListResponse>(`/api/admin/audit-logs?${query}`),
  });
}

export function useAdminAdminAuditLogs(
  page: number,
  perPage: number,
  action: string,
  tenantId: string,
) {
  const query = queryParams({
    page: String(page),
    per_page: String(perPage),
    action,
    tenant_id: tenantId,
  });
  return useQuery({
    queryKey: adminKeys.adminAuditLogs(page, perPage, action, tenantId),
    queryFn: () => api.get<AdminAdminAuditLogListResponse>(`/api/admin/audit?${query}`),
  });
}

export type {
  AdminAdminAuditLog,
  AdminAuditLog,
  AdminCrawlJob,
  AdminOverview,
  AdminRevenueReport,
  AdminStats,
  AdminSystemHealth,
  AdminTenant,
  AdminTenantDetail,
  AdminUser,
};
