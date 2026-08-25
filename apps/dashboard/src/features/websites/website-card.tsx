'use client';

import { ChevronDown, ExternalLink, Pencil, Play, RefreshCw, Trash2, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { StatusBadge } from './status-badge';
import { CrawlJobProgressBar } from './crawl-job-progress-bar';
import { KnowledgeBadge } from './knowledge-badge';
import type { CrawlJob, CrawlProgressEvent, Website } from './types';

interface WebsiteCardProps {
  website: Website;
  crawlJob: CrawlJob | null;
  crawlProgress: CrawlProgressEvent | null;
  sseConnected: boolean;
  crawlPending: boolean;
  onCrawl: (website: Website) => void;
  onEdit: (website: Website) => void;
  onDelete: (website: Website) => void;
}

export function WebsiteCard({
  website,
  crawlJob,
  crawlProgress,
  sseConnected,
  crawlPending,
  onCrawl,
  onEdit,
  onDelete,
}: WebsiteCardProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const isRunning = crawlJob?.status === 'running' || crawlPending;

  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{website.name}</h3>
          <a
            href={website.url}
            target="_blank"
            rel="noreferrer"
            className="mt-0.5 inline-flex items-center gap-1 truncate text-xs text-muted-foreground hover:text-foreground"
          >
            <span className="truncate">{website.url}</span>
            <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
          </a>
        </div>
        <StatusBadge status={website.status} />
      </div>

      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <span>
          <span className="font-medium text-foreground">{website.pages_indexed}</span>{' '}
          {website.pages_indexed === 1 ? 'page' : 'pages'} indexed
        </span>
        <span className="text-border">·</span>
        <KnowledgeBadge status={website.knowledge_status} />
      </div>

      {crawlJob ? (
        <CrawlJobProgressBar job={crawlJob} progress={crawlProgress} sseConnected={sseConnected} />
      ) : null}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={isRunning}
          onClick={() => onCrawl(website)}
        >
          {crawlPending ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : crawlJob?.status === 'failed' ? (
            <RefreshCw aria-hidden="true" />
          ) : (
            <Play aria-hidden="true" />
          )}
          {crawlPending ? 'Starting…' : crawlJob?.status === 'failed' ? 'Retry crawl' : 'Crawl now'}
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => onEdit(website)}>
          <Pencil aria-hidden="true" />
          Edit
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={() => onDelete(website)}
        >
          <Trash2 aria-hidden="true" />
          Delete
        </Button>
      </div>

      <div>
        <button
          type="button"
          className="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setDetailsOpen((o) => !o)}
          aria-expanded={detailsOpen}
        >
          <ChevronDown
            className={`size-3 transition-transform ${detailsOpen ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
          Advanced details
        </button>
        {detailsOpen ? (
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <dt>Knowledge status</dt>
            <dd className="text-right font-medium capitalize text-foreground">
              {website.knowledge_status}
            </dd>
            <dt>Chunks created</dt>
            <dd className="text-right font-medium text-foreground">{website.knowledge_chunks}</dd>
            <dt>Documents embedded</dt>
            <dd className="text-right font-medium text-foreground">
              {website.knowledge_documents}
            </dd>
            <dt>Widget ID</dt>
            <dd className="text-right font-mono font-medium text-foreground">
              {website.widget_id ? (
                <span className="truncate" title={website.widget_id}>
                  {website.widget_id}
                </span>
              ) : (
                '—'
              )}
            </dd>
          </dl>
        ) : null}
      </div>
    </div>
  );
}
