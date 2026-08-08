'use client';

import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';

import { Button } from '@/components/ui/button';

import { AddWebsiteDialog } from './add-website-dialog';
import { useCrawlJob, useDeleteWebsite, useStartCrawl, useWebsites, websitesKeys } from './hooks';
import { WebsiteCard } from './website-card';
import type { Website } from './types';

const TERMINAL_CRAWL_STATUSES = new Set(['completed', 'failed']);

export function WebsiteList() {
  const { data, isPending, isError, error, refetch } = useWebsites();
  const deleteWebsite = useDeleteWebsite();
  const startCrawl = useStartCrawl();
  const queryClient = useQueryClient();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Website | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [pendingWebsiteId, setPendingWebsiteId] = useState<string | null>(null);
  const [crawlError, setCrawlError] = useState<string | null>(null);

  const crawlJob = useCrawlJob(activeJobId);

  const websites = data ?? [];

  useEffect(() => {
    if (crawlJob.data && TERMINAL_CRAWL_STATUSES.has(crawlJob.data.status)) {
      void queryClient.invalidateQueries({ queryKey: websitesKeys.all });
    }
  }, [crawlJob.data, queryClient]);

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
      await deleteWebsite.mutateAsync(website.id);
    }
  }

  async function handleCrawl(website: Website) {
    setCrawlError(null);
    setPendingWebsiteId(website.id);
    try {
      const result = await startCrawl.mutateAsync(website.id);
      setActiveJobId(result.crawl_job_id);
    } catch (e) {
      setCrawlError(e instanceof Error ? e.message : 'Failed to start crawl.');
    } finally {
      setPendingWebsiteId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Websites</h1>
          <p className="text-sm text-muted-foreground">
            Connect a website to build its AI assistant.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus aria-hidden="true" />
          Add website
        </Button>
      </div>

      {crawlError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          {crawlError}
        </div>
      ) : null}

      {isPending ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading websites…
        </p>
      ) : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">{error?.message ?? 'Failed to load websites.'}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError && websites.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-10 text-center">
          <p className="font-medium">No websites yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Add your first website to start building its AI assistant.
          </p>
          <Button variant="outline" onClick={openCreate}>
            <Plus aria-hidden="true" />
            Add your first website
          </Button>
        </div>
      ) : null}

      {!isPending && !isError && websites.length > 0 ? (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {websites.map((website) => (
            <li key={website.id}>
              <WebsiteCard
                website={website}
                crawlJob={crawlJob.data?.website_id === website.id ? crawlJob.data : null}
                crawlPending={pendingWebsiteId === website.id}
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
    </div>
  );
}
