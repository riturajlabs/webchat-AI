'use client';

import { useEffect, useState } from 'react';
import { LogOut, Search, UserX } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/error-state';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

import { ConfirmDialog } from './confirm-dialog';
import { formatDate, statusLabel } from './format';
import { useAdminForceLogout, useAdminSuspendUser, useAdminUsers, type AdminUser } from './hooks';

const DEFAULT_PER_PAGE = 20;
const SEARCH_DEBOUNCE_MS = 300;
const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'active', label: 'Active' },
  { value: 'suspended', label: 'Suspended' },
];

type UserAction = 'suspend' | 'force-logout';

export function UserPanel() {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [pendingUser, setPendingUser] = useState<AdminUser | null>(null);
  const [pendingAction, setPendingAction] = useState<UserAction | null>(null);

  const suspendUser = useAdminSuspendUser();
  const forceLogout = useAdminForceLogout();

  const { data, isPending, isError, error, refetch } = useAdminUsers(
    page,
    DEFAULT_PER_PAGE,
    search,
    statusFilter,
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const users = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / DEFAULT_PER_PAGE));
  const hasFilters = Boolean(search || statusFilter);

  async function handleAction() {
    if (!pendingUser || !pendingAction) {
      return;
    }
    try {
      if (pendingAction === 'suspend') {
        await suspendUser.mutateAsync({
          tenantId: pendingUser.tenant_id,
          userId: pendingUser.id,
        });
        toast.success(`${pendingUser.name} suspended`);
      } else {
        await forceLogout.mutateAsync({
          tenantId: pendingUser.tenant_id,
          userId: pendingUser.id,
        });
        toast.success(`${pendingUser.name} signed out of all devices`);
      }
      setPendingUser(null);
      setPendingAction(null);
    } catch {
      toast.error(
        pendingAction === 'suspend' ? 'Failed to suspend user' : 'Failed to force logout',
      );
      setPendingUser(null);
      setPendingAction(null);
    }
  }

  const confirmTitle =
    pendingAction === 'suspend'
      ? `Suspend ${pendingUser?.name ?? 'user'}?`
      : `Force logout ${pendingUser?.name ?? 'user'}?`;

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>Users</CardTitle>
          <CardDescription>Accounts across all workspaces (ADR-006).</CardDescription>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="sm:w-64">
            <Label htmlFor="user-search" className="sr-only">
              Search users
            </Label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                id="user-search"
                type="search"
                placeholder="Search by name or email…"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                className="pl-9"
              />
            </div>
          </div>
          <div className="sm:w-44">
            <Label htmlFor="user-status-filter" className="sr-only">
              Filter by status
            </Label>
            <select
              id="user-status-filter"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(1);
              }}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
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
          <div role="status" aria-label="Loading users" className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((index) => (
              <div key={index} className="h-12 rounded-lg border bg-card p-4 shadow-sm">
                <Skeleton className="h-4 w-48" />
              </div>
            ))}
          </div>
        ) : null}

        {isError ? (
          <ErrorState
            message={error?.message ?? 'Failed to load users.'}
            onRetry={() => void refetch()}
          />
        ) : null}

        {!isPending && !isError && users.length === 0 ? (
          hasFilters ? (
            <EmptyState
              icon={UserX}
              title="No matching users"
              description="Try a different name, email, or status filter."
              actionLabel="Clear filters"
              onAction={() => {
                setSearchInput('');
                setSearch('');
                setStatusFilter('');
                setPage(1);
              }}
            />
          ) : (
            <EmptyState
              icon={UserX}
              title="No users yet"
              description="Accounts will appear here."
            />
          )
        ) : null}

        {!isPending && !isError && users.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Name
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Email
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Role
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Status
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Joined
                    </th>
                    <th scope="col" className="py-2 text-right font-medium">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id} className="border-b">
                      <td className="py-3 pr-4 font-medium">{user.name}</td>
                      <td className="py-3 pr-4 text-muted-foreground">{user.email}</td>
                      <td className="py-3 pr-4 capitalize">{user.role}</td>
                      <td className="py-3 pr-4">
                        <span
                          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                            user.status === 'active'
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {statusLabel(user.status)}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">
                        {formatDate(user.created_at)}
                      </td>
                      <td className="py-3">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={user.status === 'suspended'}
                            onClick={() => {
                              setPendingUser(user);
                              setPendingAction('suspend');
                            }}
                          >
                            <UserX aria-hidden="true" />
                            Suspend
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setPendingUser(user);
                              setPendingAction('force-logout');
                            }}
                          >
                            <LogOut aria-hidden="true" />
                            Force logout
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
                <p className="text-sm text-muted-foreground">{data?.total ?? 0} users</p>
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

      <ConfirmDialog
        open={pendingUser !== null && pendingAction !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingUser(null);
            setPendingAction(null);
          }
        }}
        onConfirm={() => void handleAction()}
        title={confirmTitle}
        description={
          pendingAction === 'suspend'
            ? `${pendingUser?.name ?? 'This user'} will be locked out until reactivated.`
            : `${pendingUser?.name ?? 'This user'} will be signed out of all devices; their account remains active.`
        }
        confirmLabel={pendingAction === 'suspend' ? 'Suspend user' : 'Force logout'}
        variant={pendingAction === 'suspend' ? 'destructive' : 'default'}
        isPending={pendingAction === 'suspend' ? suspendUser.isPending : forceLogout.isPending}
      />
    </Card>
  );
}
