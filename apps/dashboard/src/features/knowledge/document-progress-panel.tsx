'use client';

import {
  CheckCircle2,
  Circle,
  Clock4,
  ExternalLink,
  Loader2,
  RotateCcw,
  XCircle,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

import { useKnowledgeDocuments, useRetryDocument } from './hooks';
import type { KnowledgeDocument, KnowledgeDocumentStatus } from './types';

const STATUS_RANK: Record<KnowledgeDocumentStatus, number> = {
  processing: 0,
  pending: 1,
  rate_limited: 2,
  failed: 3,
  completed: 4,
};

const STATUS_LABELS: Record<KnowledgeDocumentStatus, string> = {
  completed: 'Completed',
  processing: 'Processing',
  pending: 'Pending',
  rate_limited: 'Retry scheduled',
  failed: 'Failed',
};

function DocumentStatusBadge({ status }: { status: KnowledgeDocumentStatus }) {
  const styles: Record<KnowledgeDocumentStatus, string> = {
    completed: 'bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300',
    processing: 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
    pending: 'bg-muted text-muted-foreground',
    rate_limited: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400',
    failed: 'bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300',
  };
  const icon =
    status === 'completed' ? (
      <CheckCircle2 className="size-3 shrink-0" aria-hidden="true" />
    ) : status === 'processing' ? (
      <Loader2 className="size-3 shrink-0 animate-spin" aria-hidden="true" />
    ) : status === 'failed' ? (
      <XCircle className="size-3 shrink-0" aria-hidden="true" />
    ) : status === 'pending' ? (
      <Circle className="size-3 shrink-0" aria-hidden="true" />
    ) : (
      <Clock4 className="size-3 shrink-0" aria-hidden="true" />
    );

  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        styles[status],
      )}
    >
      {icon}
      {STATUS_LABELS[status]}
    </span>
  );
}

function DocumentCount({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('text-sm font-semibold tabular-nums', className)}>{value}</dd>
    </div>
  );
}

function CurrentProcessing({ document }: { document: KnowledgeDocument }) {
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-500/30 dark:bg-amber-500/10"
    >
      <Loader2
        className="mt-0.5 size-3.5 shrink-0 animate-spin text-amber-600 dark:text-amber-400"
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="text-xs font-medium text-amber-800 dark:text-amber-300">Current processing</p>
        <span className="block min-w-0 truncate text-sm font-medium text-amber-900 dark:text-amber-200">
          {document.title || document.url}
        </span>
        <p className="text-xs text-amber-700 dark:text-amber-400">Generating embeddings…</p>
      </div>
    </div>
  );
}

function DocumentRow({
  document,
  onRetry,
  retrying,
}: {
  document: KnowledgeDocument;
  onRetry: (documentId: string) => void;
  retrying: boolean;
}) {
  const failed = document.status === 'failed';
  return (
    <li className="flex flex-col gap-1 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <DocumentStatusBadge status={document.status} />
        <a
          href={document.url}
          target="_blank"
          rel="noreferrer"
          className={cn(
            'inline-flex min-w-0 items-center gap-1 text-sm hover:underline',
            failed ? 'text-destructive' : 'text-foreground',
          )}
        >
          <span className="min-w-0 truncate">{document.title || document.url}</span>
          <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
        </a>
      </div>
      {failed ? (
        <div className="flex items-center justify-between gap-2 pl-9">
          <p className="min-w-0 truncate text-xs text-destructive">
            {document.failure_reason ?? 'Unknown error'}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shrink-0"
            disabled={retrying}
            onClick={() => onRetry(document.id)}
          >
            <RotateCcw className="size-3" aria-hidden="true" />
            {retrying ? 'Retrying…' : 'Retry'}
          </Button>
        </div>
      ) : null}
    </li>
  );
}

interface DocumentProgressPanelProps {
  websiteId: string;
  /** Optional class name so consumers can constrain height/width. */
  className?: string;
}

/**
 * Per-document embedding progress for one website. Renders truthful counts,
 * the page currently being embedded, and a scrollable list of every document
 * with its state badge. Failed pages surface their `failure_reason` exactly as
 * the API provides it. No synthetic percentage is ever displayed.
 */
export function DocumentProgressPanel({ websiteId, className }: DocumentProgressPanelProps) {
  const { data, isPending, isError, error } = useKnowledgeDocuments(websiteId);
  const retry = useRetryDocument(websiteId);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());

  if (isPending) {
    return (
      <div className={cn('space-y-2', className)} aria-label="Loading document status">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p role="alert" className={cn('text-sm text-destructive', className)}>
        {error?.message ?? 'Failed to load document status.'}
      </p>
    );
  }

  const { summary } = data;
  const sorted = [...data.documents].sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status]);
  const processing = data.documents.find((document) => document.status === 'processing') ?? null;

  const handleRetry = async (documentId: string) => {
    setRetryingIds((ids) => new Set(ids).add(documentId));
    try {
      await retry.mutateAsync(documentId);
      toast.success('Document re-queued for embedding.');
    } catch (retryError) {
      toast.error(
        retryError instanceof Error ? retryError.message : 'Failed to retry the document.',
      );
    } finally {
      setRetryingIds((ids) => {
        const next = new Set(ids);
        next.delete(documentId);
        return next;
      });
    }
  };

  const terminalCount = summary.completed + summary.failed;

  return (
    <div data-testid="document-progress-panel" className={cn('space-y-3', className)}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        <DocumentCount label="Total" value={summary.total} />
        <DocumentCount label="Completed" value={summary.completed} className="text-green-700" />
        <DocumentCount label="Processing" value={summary.processing} className="text-amber-700" />
        <DocumentCount label="Pending" value={summary.pending} />
        <DocumentCount label="Failed" value={summary.failed} className="text-red-700" />
        <DocumentCount label="Retry scheduled" value={summary.rate_limited} />
      </dl>

      {processing ? <CurrentProcessing document={processing} /> : null}

      {summary.total > 0 ? (
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Pages ({terminalCount}/{summary.total} at rest)
          </p>
          <div className="max-h-72 overflow-y-auto rounded-md border bg-muted/20">
            <ul className="divide-y divide-border/60 px-3">
              {sorted.map((document) => (
                <DocumentRow
                  key={document.id}
                  document={document}
                  onRetry={(id) => void handleRetry(id)}
                  retrying={retryingIds.has(document.id)}
                />
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export { STATUS_LABELS };
