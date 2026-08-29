'use client';

import { AlertTriangle, Brain, FileText, Globe, Loader2 } from 'lucide-react';

import type { CrawlJob, CrawlProgressEvent } from './types';

interface CrawlJobProgressBarProps {
  job: CrawlJob;
  progress: CrawlProgressEvent | null;
  sseConnected: boolean;
}

function isActive(status: CrawlJob['status']): boolean {
  return status === 'pending' || status === 'running' || status === 'processing';
}

export function CrawlJobProgressBar({ job, progress, sseConnected }: CrawlJobProgressBarProps) {
  const merged = sseConnected ? progress : null;
  const pagesCompleted = merged?.pages_completed ?? job.pages_completed ?? 0;
  const pagesTotal = merged?.pages_total ?? job.pages_total ?? 0;
  const status = merged?.status ?? job.status;

  if (isActive(job.status)) {
    return (
      <div role="status" className="flex flex-col gap-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <Loader2 className="size-3 animate-spin" aria-hidden="true" />
          <span className="font-medium">
            {status === 'started' && 'Starting\u2026'}
            {status === 'fetching' && 'Fetching pages\u2026'}
            {status === 'extracting' && 'Extracting content\u2026'}
            {status === 'embedding' && 'Generating embeddings\u2026'}
            {status === 'processing' && 'Processing\u2026'}
            {status === 'running' && 'Crawling\u2026'}
            {status === 'pending' && 'Crawling\u2026'}
          </span>
        </div>

        {status === 'fetching' && pagesTotal > 0 ? (
          <div className="flex items-center gap-2">
            <Globe className="size-3 shrink-0" aria-hidden="true" />
            <span>
              {pagesCompleted} / {pagesTotal} pages
            </span>
          </div>
        ) : status === 'extracting' ? (
          <div className="flex items-center gap-2">
            <FileText className="size-3 shrink-0" aria-hidden="true" />
            <span>Extracting page content</span>
          </div>
        ) : status === 'embedding' ? (
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
    );
  }

  if (job.status === 'failed') {
    return (
      <div
        role="alert"
        className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive"
      >
        <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
        <p>{job.error_message ?? `Crawl failed \u2014 ${job.errors.length} page(s) had errors.`}</p>
      </div>
    );
  }

  return null;
}
