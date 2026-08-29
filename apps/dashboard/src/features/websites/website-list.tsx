'use client';

import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';

import { AddWebsiteDialog } from './add-website-dialog';
import { ConfirmDialog } from '@/features/admin/confirm-dialog';
import {
  TERMINAL_CRAWL_STATUSES,
  useCrawlJob,
  useCrawlProgress,
  useDeleteWebsite,
  useStartCrawl,
  useWebsites,
  websitesKeys,
} from './hooks';
import { WebsiteCard } from './website-card';
import type { CrawlJob, CrawlProgressEvent, Website } from './types';

/* ------------------------------------------------------------------ */
/*  SessionStorage persistence for active crawl jobs (Phase 7)          */
/* ------------------------------------------------------------------ */

const ACTIVE_JOBS_KEY = 'webchat_active_crawl_jobs';

function loadActiveJobs(): Map<string, string> {
  try {
    const raw = sessionStorage.getItem(ACTIVE_JOBS_KEY);
    if (!raw) return new Map();
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) return new Map(parsed as [string, string][]);
    return new Map();
  } catch {
    return new Map();
  }
}

function saveActiveJobs(jobs: Map<string, string>): void {
  try {
    if (jobs.size === 0) {
      sessionStorage.removeItem(ACTIVE_JOBS_KEY);
    } else {
      sessionStorage.setItem(ACTIVE_JOBS_KEY, JSON.stringify([...jobs]));
    }
  } catch {
    // sessionStorage may be unavailable; silently ignore.
  }
}

/* ------------------------------------------------------------------ */
/*  CrawlJobTracker — calls hooks for a single job, passes state down  */
/* ------------------------------------------------------------------ */

function CrawlJobTracker({
  jobId,
  onJobCompleted,
  children,
}: {
  jobId: string;
  onJobCompleted?: (websiteId: string) => void;
  children: (state: {
    crawlJob: CrawlJob;
    crawlProgress: CrawlProgressEvent | null;
    sseConnected: boolean;
  }) => React.ReactNode;
}) {
  const { progress, connected } = useCrawlProgress(jobId);
  // Phase 8: pass sseConnected so polling is disabled while SSE provides
  // real-time updates. Falls back to 3s polling when SSE is disconnected.
  const { data } = useCrawlJob(jobId, connected);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (data && TERMINAL_CRAWL_STATUSES.has(data.status)) {
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
      onJobCompleted?.(data.website_id);
    }
  }, [data, queryClient, onJobCompleted]);

  if (!data) return null;

  return <>{children({ crawlJob: data, crawlProgress: progress, sseConnected: connected })}</>;
}

/* ------------------------------------------------------------------ */
/*  WebsiteList                                                         */
/* ------------------------------------------------------------------ */

export function WebsiteList() {
  const { data, isPending, isError, error, refetch } = useWebsites();
  const deleteWebsite = useDeleteWebsite();
  const startCrawl = useStartCrawl();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Website | null>(null);
  const [activeJobs, setActiveJobs] = useState<Map<string, string>>(loadActiveJobs);
  const [pendingWebsiteId, setPendingWebsiteId] = useState<string | null>(null);
  const [crawlError, setCrawlError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Website | null>(null);

  const websites = data ?? [];

  // Persist activeJobs to sessionStorage whenever they change.
  useEffect(() => {
    saveActiveJobs(activeJobs);
  }, [activeJobs]);

  function openCreate() {
    setEditing(null);
    setDialogOpen(true);
  }

  function openEdit(website: Website) {
    setEditing(website);
    setDialogOpen(true);
  }

  function closeDialog() {
    setDialogOpen(false);
    setEditing(null);
  }

  async function handleDelete(website: Website) {
    setDeleteTarget(website);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await deleteWebsite.mutateAsync(deleteTarget.id);
      toast.success(`Deleted "${deleteTarget.name}"`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete website.');
    } finally {
      setDeleteTarget(null);
    }
  }

  async function handleCrawl(website: Website) {
    setCrawlError(null);
    setPendingWebsiteId(website.id);
    try {
      const result = await startCrawl.mutateAsync(website.id);
      setActiveJobs((prev) => {
        const next = new Map(prev);
        next.set(website.id, result.crawl_job_id);
        return next;
      });
      toast.success(`Crawl started for "${website.name}"`);
    } catch (e) {
      setCrawlError(e instanceof Error ? e.message : 'Failed to start crawl.');
      toast.error(e instanceof Error ? e.message : 'Failed to start crawl.');
    } finally {
      setPendingWebsiteId(null);
    }
  }

  function renderWebsiteCard(website: Website) {
    const jobId = activeJobs.get(website.id);

    const card = (
      <WebsiteCard
        website={website}
        crawlJob={null}
        crawlProgress={null}
        sseConnected={false}
        crawlPending={pendingWebsiteId === website.id}
        onCrawl={(site) => void handleCrawl(site)}
        onEdit={openEdit}
        onDelete={(site) => void handleDelete(site)}
      />
    );

    if (!jobId) return card;

    return (
      <CrawlJobTracker
        key={jobId}
        jobId={jobId}
        onJobCompleted={(completedWebsiteId) => {
          setCrawlError(null);
          // Remove completed/failed jobs from active jobs so they don't persist
          // forever in sessionStorage.
          setActiveJobs((prev) => {
            const next = new Map(prev);
            next.delete(completedWebsiteId);
            return next;
          });
        }}
      >
        {({ crawlJob, crawlProgress, sseConnected }) => (
          <WebsiteCard
            website={website}
            crawlJob={crawlJob}
            crawlProgress={crawlProgress}
            sseConnected={sseConnected}
            crawlPending={pendingWebsiteId === website.id}
            onCrawl={(site) => void handleCrawl(site)}
            onEdit={openEdit}
            onDelete={(site) => void handleDelete(site)}
          />
        )}
      </CrawlJobTracker>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Websites"
        description="Connect a website to build its AI assistant."
        actions={
          <Button onClick={openCreate}>
            <Plus aria-hidden="true" />
            Add website
          </Button>
        }
      />

      {crawlError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          {crawlError}
        </div>
      ) : null}

      {isPending ? (
        <div
          role="status"
          aria-label="Loading websites"
          className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className="flex h-full flex-col gap-4 rounded-lg border bg-card p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="h-4 w-48" />
                </div>
                <Skeleton className="h-5 w-16" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-20" />
              </div>
              <div className="mt-auto flex gap-2">
                <Skeleton className="h-8 w-24" />
                <Skeleton className="h-8 w-16" />
                <Skeleton className="h-8 w-16" />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load websites.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError && websites.length === 0 ? (
        <EmptyState
          icon={Plus}
          title="No websites yet"
          description="Add your first website to start building its AI assistant."
          actionLabel="Add your first website"
          onAction={openCreate}
        />
      ) : null}

      {!isPending && !isError && websites.length > 0 ? (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {websites.map((website) => (
            <li key={website.id}>{renderWebsiteCard(website)}</li>
          ))}
        </ul>
      ) : null}

      <AddWebsiteDialog
        key={editing?.id ?? 'new'}
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            closeDialog();
          } else {
            setDialogOpen(true);
          }
        }}
        website={editing}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        onConfirm={() => void confirmDelete()}
        title="Delete website"
        description={`Delete "${deleteTarget?.name ?? ''}"? This also removes its widget.`}
        confirmLabel="Delete"
        variant="destructive"
        isPending={deleteWebsite.isPending}
      />
    </div>
  );
}
