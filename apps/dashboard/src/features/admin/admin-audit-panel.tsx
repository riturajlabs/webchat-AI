'use client';

import { useState } from 'react';
import { ScrollText } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/error-state';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

import { formatDateTime } from './format';
import { useAdminAdminAuditLogs } from './hooks';

const DEFAULT_PER_PAGE = 20;

/** Dedicated platform admin trail (Phase 15 `/api/admin/audit`). */
export function AdminAuditPanel() {
  const [page, setPage] = useState(1);
  const [actionInput, setActionInput] = useState('');
  const [action, setAction] = useState('');
  const [tenantInput, setTenantInput] = useState('');
  const [tenantId, setTenantId] = useState('');

  const { data, isPending, isError, error, refetch } = useAdminAdminAuditLogs(
    page,
    DEFAULT_PER_PAGE,
    action,
    tenantId,
  );

  const logs = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / DEFAULT_PER_PAGE));
  const hasFilters = Boolean(action || tenantId);

  function applyFilters() {
    setAction(actionInput.trim().toUpperCase());
    setTenantId(tenantInput.trim());
    setPage(1);
  }

  function clearFilters() {
    setActionInput('');
    setAction('');
    setTenantInput('');
    setTenantId('');
    setPage(1);
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <CardTitle>Admin audit trail</CardTitle>
          <CardDescription>
            Platform operator actions (suspend, activate, plan change), newest first (Phase 15).
          </CardDescription>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="sm:w-52">
            <Label htmlFor="admin-audit-action-filter" className="sr-only">
              Filter by action
            </Label>
            <Input
              id="admin-audit-action-filter"
              type="text"
              placeholder="Action (e.g. TENANT_SUSPENDED)…"
              value={actionInput}
              onChange={(event) => setActionInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  applyFilters();
                }
              }}
            />
          </div>
          <div className="sm:w-52">
            <Label htmlFor="admin-audit-tenant-filter" className="sr-only">
              Filter by tenant
            </Label>
            <Input
              id="admin-audit-tenant-filter"
              type="text"
              placeholder="Tenant id…"
              value={tenantInput}
              onChange={(event) => setTenantInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  applyFilters();
                }
              }}
            />
          </div>
          <Button variant="outline" size="sm" onClick={applyFilters}>
            Filter
          </Button>
          {hasFilters ? (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {isPending ? (
          <div role="status" aria-label="Loading admin audit log" className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((index) => (
              <div key={index} className="h-12 rounded-lg border bg-card p-4 shadow-sm">
                <Skeleton className="h-4 w-48" />
              </div>
            ))}
          </div>
        ) : null}

        {isError ? (
          <ErrorState
            message={error?.message ?? 'Failed to load admin audit log.'}
            onRetry={() => void refetch()}
          />
        ) : null}

        {!isPending && !isError && logs.length === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={ScrollText}
              title="No matching admin actions"
              description="Try different filters."
              actionLabel="Clear filters"
              onAction={clearFilters}
            />
          ) : (
            <EmptyState
              icon={ScrollText}
              title="No admin actions yet"
              description="Tenant operations by platform operators are recorded here."
            />
          )
        ) : null}

        {!isPending && !isError && logs.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="py-2 pr-4 font-medium">
                      When
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Action
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Actor
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Tenant
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      User
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Plan
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      IP
                    </th>
                    <th scope="col" className="py-2 font-medium">
                      User agent
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <tr key={log.id} className="border-b">
                      <td className="py-3 pr-4 whitespace-nowrap text-muted-foreground">
                        {formatDateTime(log.created_at)}
                      </td>
                      <td className="py-3 pr-4">
                        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                          {log.action}
                        </code>
                      </td>
                      <td className="py-3 pr-4 font-mono text-xs">{log.actor_user_id ?? '—'}</td>
                      <td className="py-3 pr-4 font-mono text-xs">{log.tenant_id ?? '—'}</td>
                      <td className="py-3 pr-4 font-mono text-xs">{log.user_id ?? '—'}</td>
                      <td className="py-3 pr-4 font-mono text-xs">{log.plan_id ?? '—'}</td>
                      <td className="py-3 pr-4 font-mono text-xs">{log.ip_address ?? '—'}</td>
                      <td className="max-w-56 truncate py-3 text-xs text-muted-foreground">
                        {log.user_agent ?? '—'}
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
                <p className="text-sm text-muted-foreground">{data?.total ?? 0} events</p>
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
    </Card>
  );
}
