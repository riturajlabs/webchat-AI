'use client';

import {
  AlertTriangle,
  ExternalLink,
  FileText,
  Globe,
  Loader2,
  Brain,
  Pencil,
  Play,
  RefreshCw,
  Trash2,
} from 'lucide-react';

import { Button } from '@/components/ui/button';

import { StatusBadge } from './status-badge';
import type { CrawlJob, CrawlProgressEvent, Website } from './types';

function formatDate(value: string | null): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '—';
  }
  return date.toLocaleDateString();
}

function isActive(job: CrawlJob): boolean {
  return job.status === 'pending' || job.status === 'running' || job.status === 'processing';
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
}: {
  website: Website;
  crawlJob: CrawlJob | null;
  crawlProgress: CrawlProgressEvent | null;
  sseConnected: boolean;
  crawlPending: boolean;
  onCrawl: (website: Website) => void;
  onEdit: (website: Website) => void;
  onDelete: (website: Website) => void;
}) {
  const crawling = crawlJob !== null && isActive(crawlJob);
  const crawlFailed = crawlJob?.status === 'failed';

  // Merge SSE progress with polling data: SSE takes priority when connected
  const progress = sseConnected ? crawlProgress : null;
  const pagesCompleted = progress?.pages_completed ?? crawlJob?.pages_completed ?? 0;
  const pagesTotal = progress?.pages_total ?? crawlJob?.pages_total ?? 0;
  const progressStatus = progress?.status ?? crawlJob?.status ?? null;

  return (
    <article className="flex h-full flex-col gap-4 rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{website.name}</h3>
          <a
            href={website.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex max-w-full items-center gap-1 truncate text-sm text-muted-foreground hover:text-foreground"
          >
            <span className="truncate">{website.url}</span>
            <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
          </a>
        </div>
        <StatusBadge status={website.status} />
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div>
          <dt className="text-muted-foreground">Pages indexed</dt>
          <dd className="font-medium">{website.pages_indexed}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Last crawled</dt>
          <dd className="font-medium">{formatDate(website.last_crawled_at)}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-muted-foreground">Widget id</dt>
          <dd className="truncate font-mono text-[11px]">{website.widget_id}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Knowledge status</dt>
          <dd className="font-medium capitalize">{website.knowledge_status}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Chunks created</dt>
          <dd className="font-medium">{website.knowledge_chunks}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-muted-foreground">Documents embedded</dt>
          <dd className="font-medium">{website.knowledge_documents}</dd>
        </div>
      </dl>

      {crawling && crawlJob ? (
        <div role="status" className="flex flex-col gap-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <Loader2 className="size-3 animate-spin" aria-hidden="true" />
            <span className="font-medium">
              {progressStatus === 'fetching' && 'Fetching pages\u2026'}
              {progressStatus === 'extracting' && 'Extracting content\u2026'}
              {progressStatus === 'embedding' && 'Generating embeddings\u2026'}
              {progressStatus === 'processing' && 'Processing\u2026'}
              {progressStatus === 'running' && 'Crawling\u2026'}
              {!progressStatus && 'Crawling\u2026'}
            </span>
          </div>

          {progressStatus === 'fetching' && pagesTotal > 0 ? (
            <div className="flex items-center gap-2">
              <Globe className="size-3 shrink-0" aria-hidden="true" />
              <span>
                {pagesCompleted} / {pagesTotal} pages
              </span>
            </div>
          ) : progressStatus === 'extracting' ? (
            <div className="flex items-center gap-2">
              <FileText className="size-3 shrink-0" aria-hidden="true" />
              <span>Extracting page content</span>
            </div>
          ) : progressStatus === 'embedding' ? (
            <div className="flex items-center gap-2">
              <Brain className="size-3 shrink-0" aria-hidden="true" />
              <span>Generating embeddings</span>
            </div>
          ) : pagesTotal > 0 ? (
            <div className="flex items-center gap-2">
              <Globe className="size-3 shrink-0" aria-hidden="true" />
              <span>
                {pagesCompleted} / {pagesTotal} pages
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Globe className="size-3 shrink-0" aria-hidden="true" />
              <span>{pagesCompleted} pages found</span>
            </div>
          )}

          {pagesTotal > 0 ? (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{
                  width: `${Math.min(100, Math.round((pagesCompleted / pagesTotal) * 100))}%`,
                }}
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {crawlFailed && crawlJob ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive"
        >
          <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          <p>
            {crawlJob.error_message ??
              `Crawl failed — ${crawlJob.errors.length} page(s) had errors.`}
          </p>
        </div>
      ) : null}

      <div className="mt-auto flex flex-wrap gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onCrawl(website)}
          disabled={crawling || crawlPending}
        >
          {crawlPending ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : crawlFailed ? (
            <RefreshCw aria-hidden="true" />
          ) : (
            <Play aria-hidden="true" />
          )}
          {crawlPending ? 'Starting…' : crawlFailed ? 'Retry crawl' : 'Crawl now'}
        </Button>
        <Button variant="outline" size="sm" onClick={() => onEdit(website)}>
          <Pencil aria-hidden="true" />
          Edit
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={() => onDelete(website)}
        >
          <Trash2 aria-hidden="true" />
          Delete
        </Button>
      </div>
    </article>
  );
}
