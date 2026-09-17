'use client';

import { ChevronDown, ExternalLink, Pencil, Play, RefreshCw, Trash2, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { useKnowledgeReadiness } from '@/features/knowledge/hooks';
import { WebsiteStatusBadge } from './status-badge';
import { CrawlJobProgressBar, GeneratingEmbeddingsStatus } from './crawl-job-progress-bar';
import { KnowledgeBadge } from './knowledge-badge';
import { DEFAULT_WEBSITE_IMAGE } from './constants';
import { isEmbeddingInProgress } from './types';
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
  // The teaser is always rendered: the crawled preview image when the website
  // has one, otherwise the shared default. On an image error the src swaps to
  // the default exactly once (state is already the default, so React bails out
  // of any follow-up render — no infinite error loop).
  const [imageSrc, setImageSrc] = useState(() => website.preview_image || DEFAULT_WEBSITE_IMAGE);
  useEffect(() => {
    setImageSrc(website.preview_image || DEFAULT_WEBSITE_IMAGE);
  }, [website.preview_image]);
  // Per-document readiness derived from the documents API — the backend can
  // persist `knowledge_status = 'ready'` while sibling docs still embed, so the
  // true state comes from the documents summary, not the website flag.
  const { readiness, query } = useKnowledgeReadiness(website);
  const currentDocument = query.data?.documents.find(
    (document) => document.status === 'processing',
  );
  const isRunning = crawlJob?.status === 'running' || crawlPending;
  // A crawl that is actually in flight takes precedence over the knowledge
  // phase: the embedding block only shows once the crawl job is done (or was
  // never tracked) but the knowledge base is still being embedded. The legacy
  // `isEmbeddingInProgress` fallback covers a brief window while the per-document
  // data is still being fetched (the persisted status says `processing`).
  const embeddingActive = readiness.isEmbedding || isEmbeddingInProgress(website);
  const jobActive =
    crawlJob !== null && crawlJob.status !== 'completed' && crawlJob.status !== 'failed';

  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-4 shadow-sm">
      <div className="-m-1 overflow-hidden rounded-md border border-border/60">
        {/* eslint-disable-next-line @next/next/no-img-element -- page metadata preview image URL */}
        <img
          src={imageSrc}
          alt=""
          // Intrinsic 16:9 hint for the browser's pre-layout estimate; the
          // responsive `aspect-[16/9] w-full` classes still govern the final
          // rendered size, so the source's own aspect ratio never distorts it.
          width={640}
          height={360}
          className="aspect-[16/9] w-full object-cover"
          onError={() => setImageSrc(DEFAULT_WEBSITE_IMAGE)}
        />
      </div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{website.name}</h3>
          {website.url ? (
            <a
              href={website.url}
              target="_blank"
              rel="noreferrer"
              className="mt-0.5 flex min-w-0 items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <span className="min-w-0 truncate">{website.url}</span>
              <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
            </a>
          ) : (
            <span className="mt-0.5 block text-xs text-muted-foreground">Document chatbot</span>
          )}
        </div>
        <WebsiteStatusBadge website={website} readiness={readiness} />
      </div>

      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <span>
          <span className="font-medium text-foreground">{website.pages_indexed}</span>{' '}
          {website.pages_indexed === 1 ? 'page' : 'pages'} indexed
        </span>
        <span className="text-border">·</span>
        <KnowledgeBadge status={readiness.status} embedding={readiness.isEmbedding} />
      </div>

      {crawlJob && (crawlJob.status === 'failed' || jobActive) ? (
        <CrawlJobProgressBar job={crawlJob} progress={crawlProgress} sseConnected={sseConnected} />
      ) : embeddingActive ? (
        <GeneratingEmbeddingsStatus website={website} currentDocument={currentDocument} />
      ) : crawlJob ? (
        <CrawlJobProgressBar job={crawlJob} progress={crawlProgress} sseConnected={sseConnected} />
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {website.url && website.source_mode !== 'files' ? (
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
            {crawlPending
              ? 'Starting…'
              : crawlJob?.status === 'failed'
                ? 'Retry crawl'
                : 'Crawl now'}
          </Button>
        ) : null}
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
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <dt>Knowledge status</dt>
              <dd className="text-right font-medium capitalize text-foreground min-w-0">
                {readiness.status ?? website.knowledge_status}
              </dd>
              <dt>Chunks created</dt>
              <dd className="text-right font-medium text-foreground min-w-0">
                {website.knowledge_chunks}
              </dd>
              <dt>Documents embedded</dt>
              <dd className="text-right font-medium text-foreground min-w-0">
                {website.knowledge_documents}
              </dd>
              <dt>Widget ID</dt>
              <dd className="min-w-0 max-w-full text-right font-mono font-medium text-foreground">
                {website.widget_id ? (
                  <span className="break-all" title={website.widget_id}>
                    {website.widget_id}
                  </span>
                ) : (
                  '—'
                )}
              </dd>
            </dl>
          </div>
        ) : null}
      </div>
    </div>
  );
}
