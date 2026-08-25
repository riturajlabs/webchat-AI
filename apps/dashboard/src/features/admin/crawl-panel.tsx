'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/error-state';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

import { formatDateTime, formatNumber, statusLabel } from './format';
import { useAdminCrawlJobs } from './hooks';

const DEFAULT_PER_PAGE = 20;
const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
];

export function CrawlPanel() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');

  const { data, isPending, isError, error, refetch } = useAdminCrawlJobs(
    page,
    DEFAULT_PER_PAGE,
    statusFilter,
  );

  const jobs = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / DEFAULT_PER_PAGE));

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>Crawl queue</CardTitle>
          <CardDescription>Global crawl jobs across all tenants (ADR-006).</CardDescription>
        </div>
        <div className="sm:w-44">
          <Label htmlFor="crawl-status-filter" className="sr-only">
            Filter by status
          </Label>
          <select
            id="crawl-status-filter"
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
      </CardHeader>
      <CardContent>
        {isPending ? (
          <div role="status" aria-label="Loading crawl jobs" className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((index) => (
              <div key={index} className="h-12 rounded-lg border bg-card p-4 shadow-sm">
                <Skeleton className="h-4 w-48" />
              </div>
            ))}
          </div>
        ) : null}

        {isError ? (
          <ErrorState
            message={error?.message ?? 'Failed to load crawl jobs.'}
            onRetry={() => void refetch()}
          />
        ) : null}

        {!isPending && !isError && jobs.length === 0 ? (
          statusFilter ? (
            <EmptyState
              icon={Loader2}
              title="No matching crawl jobs"
              description="No jobs with this status right now."
              actionLabel="Clear filter"
              onAction={() => {
                setStatusFilter('');
                setPage(1);
              }}
            />
          ) : (
            <EmptyState
              icon={Loader2}
              title="No crawl jobs"
              description="Crawl jobs created by tenants will appear here."
            />
          )
        ) : null}

        {!isPending && !isError && jobs.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Status
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Tenant
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Progress
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Started
                    </th>
                    <th scope="col" className="py-2 font-medium">
                      Error
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id} className="border-b">
                      <td className="py-3 pr-4">
                        <span
                          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                            job.status === 'failed'
                              ? 'bg-red-100 text-red-800'
                              : job.status === 'completed'
                                ? 'bg-green-100 text-green-800'
                                : 'bg-blue-100 text-blue-800'
                          }`}
                        >
                          {statusLabel(job.status)}
                        </span>
                      </td>
                      <td className="py-3 pr-4 font-mono text-xs">{job.tenant_id}</td>
                      <td className="py-3 pr-4 text-muted-foreground">
                        {formatNumber(job.pages_completed)} / {formatNumber(job.pages_total)} pages
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">
                        {formatDateTime(job.created_at)}
                      </td>
                      <td className="max-w-56 truncate py-3 text-xs text-muted-foreground">
                        {job.error_message ?? '—'}
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
                <p className="text-sm text-muted-foreground">{data?.total ?? 0} jobs</p>
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
