'use client';

import { useEffect, useRef, useState } from 'react';
import { Building2, Eye, Search, X } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/error-state';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { useAccessibleDialog } from '@/hooks/use-accessible-dialog';

import { ConfirmDialog } from './confirm-dialog';
import { formatDate, statusLabel } from './format';
import {
  useAdminActivateTenant,
  useAdminChangeTenantPlan,
  useAdminSuspendTenant,
  useAdminTenantDetail,
  useAdminTenants,
  type AdminTenant,
  type AdminTenantDetail,
} from './hooks';

const DEFAULT_PER_PAGE = 20;
const SEARCH_DEBOUNCE_MS = 300;

const PLAN_OPTIONS = [
  { value: '', label: 'All plans' },
  { value: 'free', label: 'Free' },
  { value: 'pro', label: 'Pro' },
  { value: 'enterprise', label: 'Enterprise' },
];

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'active', label: 'Active' },
  { value: 'suspended', label: 'Suspended' },
];

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="text-sm">{value}</p>
    </div>
  );
}

function TenantDetailDialog({
  tenantId,
  onClose,
}: {
  tenantId: string | null;
  onClose: () => void;
}) {
  const { data, isPending, isError, refetch } = useAdminTenantDetail(tenantId);
  const changePlan = useAdminChangeTenantPlan();
  const [planInput, setPlanInput] = useState('');
  const contentRef = useRef<HTMLDivElement>(null);

  useAccessibleDialog({
    open: Boolean(tenantId),
    onClose,
    contentRef,
  });

  useEffect(() => {
    setPlanInput(data?.plan ?? '');
  }, [data?.plan]);

  if (!tenantId) {
    return null;
  }

  async function handleChangePlan() {
    if (!data || planInput === data.plan) {
      return;
    }
    try {
      await changePlan.mutateAsync({ tenantId: data.id, plan: planInput });
      toast.success(`Plan changed to ${planInput}`);
    } catch {
      toast.error('Failed to change plan');
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tenant-detail-title"
    >
      <div
        className="absolute inset-0 bg-black/50"
        data-dialog-overlay
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={contentRef}
        className="relative z-10 max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg border bg-background p-6 shadow-lg"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="tenant-detail-title" className="font-sans text-lg font-semibold">
              {data?.company_name ?? 'Tenant'}
            </h2>
            <p className="text-sm text-muted-foreground">Workspace details</p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close dialog">
            <X aria-hidden="true" />
          </Button>
        </div>

        {isPending ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-56" />
            <Skeleton className="h-4 w-32" />
          </div>
        ) : null}

        {isError ? (
          <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4">
            <p className="text-sm text-destructive">Failed to load tenant details.</p>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              Try again
            </Button>
          </div>
        ) : null}

        {!isPending && !isError && data ? (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-4">
              <DetailField label="Company" value={data.company_name} />
              <DetailField label="Status" value={statusLabel(data.status)} />
              <DetailField label="Created" value={formatDate(data.created_at)} />
            </div>
            <div className="flex items-end justify-between gap-3 rounded-md border bg-muted/30 p-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="tenant-plan-select">Plan</Label>
                <select
                  id="tenant-plan-select"
                  value={planInput}
                  onChange={(event) => setPlanInput(event.target.value)}
                  className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {PLAN_OPTIONS.filter((option) => option.value).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleChangePlan()}
                disabled={changePlan.isPending || planInput === data.plan}
              >
                {changePlan.isPending ? 'Saving…' : 'Save plan'}
              </Button>
            </div>
            <div className="grid grid-cols-3 gap-4 rounded-md bg-muted/50 p-4 text-center">
              <div>
                <p className="font-sans text-xl font-bold tracking-tight">{data.website_count}</p>
                <p className="text-xs text-muted-foreground">Websites</p>
              </div>
              <div>
                <p className="font-sans text-xl font-bold tracking-tight">{data.user_count}</p>
                <p className="text-xs text-muted-foreground">Users</p>
              </div>
              <div>
                <p className="font-sans text-xl font-bold tracking-tight">
                  {data.active_crawl_jobs}
                </p>
                <p className="text-xs text-muted-foreground">Active crawls</p>
              </div>
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">All-time usage</p>
              <div className="grid grid-cols-2 gap-4">
                <DetailField label="Conversations" value={String(data.usage.conversations)} />
                <DetailField label="Messages" value={String(data.usage.messages)} />
                <DetailField label="Input tokens" value={String(data.usage.input_tokens)} />
                <DetailField label="Output tokens" value={String(data.usage.output_tokens)} />
              </div>
            </div>
          </div>
        ) : null}

        <div className="mt-6 flex justify-end">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Workspace management (Phase 15 `/api/admin/tenants` with plan/status filters). */
export function TenantPanel() {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [planFilter, setPlanFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [detailTenantId, setDetailTenantId] = useState<string | null>(null);
  const [pendingTenant, setPendingTenant] = useState<AdminTenant | null>(null);

  const suspendTenant = useAdminSuspendTenant();
  const activateTenant = useAdminActivateTenant();
  const { data, isPending, isError, error, refetch } = useAdminTenants(
    page,
    DEFAULT_PER_PAGE,
    search,
    planFilter,
    statusFilter,
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const tenants = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / DEFAULT_PER_PAGE));
  const hasFilters = Boolean(search || planFilter || statusFilter);

  async function handleStatusToggle(tenant: AdminTenant) {
    if (!pendingTenant) {
      return;
    }
    const nextStatus = tenant.status === 'suspended' ? 'active' : 'suspended';
    try {
      if (nextStatus === 'suspended') {
        await suspendTenant.mutateAsync({ tenantId: tenant.id });
      } else {
        await activateTenant.mutateAsync({ tenantId: tenant.id });
      }
      toast.success(
        nextStatus === 'suspended'
          ? `${tenant.company_name} suspended`
          : `${tenant.company_name} activated`,
      );
      setPendingTenant(null);
    } catch {
      toast.error(`Failed to ${nextStatus === 'suspended' ? 'suspend' : 'activate'} tenant`);
      setPendingTenant(null);
    }
  }

  const isMutating = suspendTenant.isPending || activateTenant.isPending;

  function clearFilters() {
    setSearchInput('');
    setSearch('');
    setPlanFilter('');
    setStatusFilter('');
    setPage(1);
  }

  const openConfirmFor = pendingTenant
    ? pendingTenant.status === 'suspended'
      ? `Activate ${pendingTenant.company_name}?`
      : `Suspend ${pendingTenant.company_name}?`
    : '';

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <CardTitle>Tenants</CardTitle>
          <CardDescription>
            Workspaces on the platform, filterable by plan and status.
          </CardDescription>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="sm:w-60">
            <Label htmlFor="tenant-search" className="sr-only">
              Search tenants
            </Label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                id="tenant-search"
                type="search"
                placeholder="Search by company…"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                className="pl-9"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="tenant-plan-filter" className="sr-only">
              Filter by plan
            </Label>
            <select
              id="tenant-plan-filter"
              value={planFilter}
              onChange={(event) => {
                setPlanFilter(event.target.value);
                setPage(1);
              }}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:w-36"
            >
              {PLAN_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="tenant-status-filter" className="sr-only">
              Filter by status
            </Label>
            <select
              id="tenant-status-filter"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(1);
              }}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:w-36"
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <div role="status" aria-label="Loading tenants" className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((index) => (
              <div key={index} className="h-12 rounded-lg border bg-card p-4 shadow-sm">
                <Skeleton className="h-4 w-48" />
              </div>
            ))}
          </div>
        ) : null}

        {isError ? (
          <ErrorState
            message={error?.message ?? 'Failed to load tenants.'}
            onRetry={() => void refetch()}
          />
        ) : null}

        {!isPending && !isError && tenants.length === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={Building2}
              title="No matching tenants"
              description="Try different search or filters."
              actionLabel="Clear filters"
              onAction={clearFilters}
            />
          ) : (
            <EmptyState
              icon={Building2}
              title="No tenants yet"
              description="Tenants created through signup will appear here."
            />
          )
        ) : null}

        {!isPending && !isError && tenants.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Company
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Plan
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Status
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Created
                    </th>
                    <th scope="col" className="py-2 text-right font-medium">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((tenant) => (
                    <tr key={tenant.id} className="border-b">
                      <td className="py-3 pr-4 font-medium">{tenant.company_name}</td>
                      <td className="py-3 pr-4 capitalize">{tenant.plan}</td>
                      <td className="py-3 pr-4">
                        <span
                          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                            tenant.status === 'active'
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {statusLabel(tenant.status)}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">
                        {formatDate(tenant.created_at)}
                      </td>
                      <td className="py-3">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setDetailTenantId(tenant.id)}
                          >
                            <Eye aria-hidden="true" />
                            Details
                          </Button>
                          <Button
                            variant={tenant.status === 'suspended' ? 'outline' : 'destructive'}
                            size="sm"
                            onClick={() => setPendingTenant(tenant)}
                            disabled={isMutating}
                          >
                            {tenant.status === 'suspended' ? 'Activate' : 'Suspend'}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <p className="text-sm text-muted-foreground">
                  Page {data?.page ?? 1} of {totalPages}
                </p>
                <p className="text-sm text-muted-foreground">{data?.total ?? 0} tenants</p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        ) : null}
      </CardContent>

      <TenantDetailDialog tenantId={detailTenantId} onClose={() => setDetailTenantId(null)} />

      <ConfirmDialog
        open={pendingTenant !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingTenant(null);
          }
        }}
        onConfirm={() => pendingTenant && void handleStatusToggle(pendingTenant)}
        title={openConfirmFor}
        description={
          pendingTenant?.status === 'suspended'
            ? `This re-enables login and the widget for ${pendingTenant.company_name}.`
            : `Members of ${pendingTenant?.company_name ?? 'this tenant'} will be locked out of the dashboard and widget.`
        }
        confirmLabel={pendingTenant?.status === 'suspended' ? 'Activate tenant' : 'Suspend tenant'}
        variant={pendingTenant?.status === 'suspended' ? 'default' : 'destructive'}
        isPending={isMutating}
      />
    </Card>
  );
}

export type { AdminTenantDetail };
