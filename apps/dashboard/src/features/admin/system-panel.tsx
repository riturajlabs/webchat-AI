'use client';

import { Database, HardDrive, Server } from 'lucide-react';

import { ErrorState } from '@/components/ui/error-state';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import { formatDateTime, formatNumber } from './format';
import { useAdminSystemHealth } from './hooks';

function StatusBadge({ status }: { status: string }) {
  const ok = status === 'ok';
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
      }`}
    >
      {ok ? 'OK' : 'Degraded'}
    </span>
  );
}

/** System health + collection counts (Phase 15 `/api/admin/system-health`). */
export function SystemPanel() {
  const { data, isPending, isError, error, refetch } = useAdminSystemHealth();

  return (
    <div className="flex flex-col gap-6">
      {isPending ? (
        <div
          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
          role="status"
          aria-label="Loading system health"
        >
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <Card key={index}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load system health.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError && data ? (
        <>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
              <div>
                <CardTitle>Dependency probes</CardTitle>
                <CardDescription>
                  Fails closed: the platform is degraded unless every check passes. Checked{' '}
                  {formatDateTime(data.checked_at)}.
                </CardDescription>
              </div>
              <StatusBadge status={data.status} />
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-2">
                {data.checks.map((check) => (
                  <li
                    key={check.name}
                    className="flex items-center justify-between gap-3 rounded-lg border bg-muted/30 px-4 py-3"
                  >
                    <span className="flex items-center gap-2 text-sm font-medium">
                      <Database className="size-4 text-muted-foreground" aria-hidden="true" />
                      {check.name}
                    </span>
                    <StatusBadge status={check.status} />
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Collection counts</CardTitle>
              <CardDescription>Row counts per collection across the platform.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
                {Object.entries(data.counts).map(([key, value]) => (
                  <div
                    key={key}
                    className="rounded-lg border bg-card p-3 shadow-sm"
                    data-testid={`count-${key}`}
                  >
                    <p className="font-sans text-lg font-bold tracking-tight">
                      {formatNumber(value)}
                    </p>
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      {key === 'users' || key === 'chat_sessions' ? (
                        <HardDrive className="size-3" aria-hidden="true" />
                      ) : (
                        <Server className="size-3" aria-hidden="true" />
                      )}
                      {key.replaceAll('_', ' ')}
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
