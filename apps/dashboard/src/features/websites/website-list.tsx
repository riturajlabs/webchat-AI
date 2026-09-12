'use client';

import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';

import { AddWebsiteDialog } from './add-website-dialog';
import { ConfirmDialog } from '@/features/admin/confirm-dialog';
import { TERMINAL_CRAWL_STATUSES, useDeleteWebsite, useStartCrawl, useWebsites } from './hooks';
import { activeCrawlStore } from './active-crawl-store';
import { useCrawlActivity } from './crawl-activity-context';
import { WebsiteCard } from './website-card';
import type { Website } from './types';

/* ------------------------------------------------------------------ */
/*  WebsiteCardWithActivity — consumes the app-wide crawl monitor      */
/* ------------------------------------------------------------------ */

function WebsiteCardWithActivity({
  website,
  crawlPending,
  onJobTerminal,
  onCrawl,
  onEdit,
  onDelete,
}: {
  website: Website;
  crawlPending: boolean;
  onJobTerminal: () => void;
  onCrawl: (website: Website) => void;
  onEdit: (website: Website) => void;
  onDelete: (website: Website) => void;
}) {
  const { crawlJob, crawlProgress, sseConnected } = useCrawlActivity(website.id);

  // A terminal job means the crawl (or its knowledge phase) finished server
  // side — clear any transient start-crawl error banner shown for this site.
  useEffect(() => {
    if (crawlJob && TERMINAL_CRAWL_STATUSES.has(crawlJob.status)) {
      onJobTerminal();
    }
  }, [crawlJob, onJobTerminal]);

  return (
    <WebsiteCard
      website={website}
      crawlJob={crawlJob}
      crawlProgress={crawlProgress}
      sseConnected={sseConnected}
      crawlPending={crawlPending}
      onCrawl={onCrawl}
      onEdit={onEdit}
      onDelete={onDelete}
    />
  );
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
  const [pendingWebsiteId, setPendingWebsiteId] = useState<string | null>(null);
  const [crawlError, setCrawlError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Website | null>(null);

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
      // Registers the job with the app-wide monitor (single SSE stream + poll
      // per job), persisted across pages and reloads via active-crawl-store.
      activeCrawlStore.set(website.id, result.crawl_job_id);
      toast.success(`Crawl started for "${website.name}"`);
    } catch (e) {
      setCrawlError(e instanceof Error ? e.message : 'Failed to start crawl.');
      toast.error(e instanceof Error ? e.message : 'Failed to start crawl.');
    } finally {
      setPendingWebsiteId(null);
    }
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
          className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className="flex h-full min-w-0 flex-col gap-4 rounded-lg border bg-card p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="h-5 w-48" />
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
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {websites.map((website) => (
            <li key={website.id} className="min-w-0">
              <WebsiteCardWithActivity
                website={website}
                crawlPending={pendingWebsiteId === website.id}
                onJobTerminal={() => setCrawlError(null)}
                onCrawl={(site) => void handleCrawl(site)}
                onEdit={openEdit}
                onDelete={(site) => void handleDelete(site)}
              />
            </li>
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
