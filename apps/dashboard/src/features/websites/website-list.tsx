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
import {
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
/*  CrawlJobTracker — calls hooks for a single job, passes state down  */
/* ------------------------------------------------------------------ */

function CrawlJobTracker({
  jobId,
  onJobCompleted,
  children,
}: {
  jobId: string;
  onJobCompleted?: () => void;
  children: (state: {
    crawlJob: CrawlJob;
    crawlProgress: CrawlProgressEvent | null;
    sseConnected: boolean;
  }) => React.ReactNode;
}) {
  const { data } = useCrawlJob(jobId);
  const { progress, connected } = useCrawlProgress(jobId);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (data && data.status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
      onJobCompleted?.();
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
  const [activeJobs, setActiveJobs] = useState<Map<string, string>>(new Map());
  const [pendingWebsiteId, setPendingWebsiteId] = useState<string | null>(null);
  const [crawlError, setCrawlError] = useState<string | null>(null);

  const websites = data ?? [];

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
    if (window.confirm(`Delete "${website.name}"? This also removes its widget.`)) {
      try {
        await deleteWebsite.mutateAsync(website.id);
        toast.success(`Deleted "${website.name}"`);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to delete website.');
      }
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
      <CrawlJobTracker key={jobId} jobId={jobId} onJobCompleted={() => setCrawlError(null)}>
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
    </div>
  );
}
