'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Database, ExternalLink, RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { useWebsites } from '@/features/websites/hooks';
import { KnowledgeBadge } from '@/features/websites/knowledge-badge';
import type { KnowledgeStatus } from '@/features/websites/types';

import { useKnowledgeDocuments, useRetryDocument } from './hooks';
import type { KnowledgeDocumentSummary } from './types';

function KnowledgeStat({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardHeader className="space-y-0 pb-2">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="font-sans text-3xl font-bold tracking-tight">{value}</p>
      </CardContent>
    </Card>
  );
}

function DocumentSummary({ summary }: { summary: KnowledgeDocumentSummary }) {
  return (
    <div className="grid gap-2 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-muted-foreground">Total</dt>
        <dd className="font-medium">{summary.total}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Processed</dt>
        <dd className="font-medium text-green-700">{summary.completed}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Failed</dt>
        <dd className="font-medium text-red-700">{summary.failed}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Pending</dt>
        <dd className="font-medium">{summary.pending + summary.processing}</dd>
      </div>
    </div>
  );
}

function ProcessingProgress({ summary }: { summary: KnowledgeDocumentSummary }) {
  if (summary.total === 0 || (summary.pending === 0 && summary.processing === 0)) {
    return null;
  }
  const done = summary.completed + summary.failed;
  const ratio = Math.min(1, done / summary.total);
  return (
    <div className="space-y-1" role="status" aria-label="Embedding progress">
      <p className="text-xs text-muted-foreground">
        Embedding… {done}/{summary.total} documents processed
      </p>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(ratio * 100)}
      >
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  );
}

interface FailedDocumentProps {
  documentId: string;
  url: string;
  reason: string;
  onRetry: (documentId: string) => void;
  retrying: boolean;
}

function FailedDocument({ documentId, url, reason, onRetry, retrying }: FailedDocumentProps) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex max-w-full items-center gap-1 truncate text-sm font-medium hover:underline"
        >
          <span className="truncate">{url}</span>
          <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
        </a>
        <p className="mt-0.5 truncate text-xs text-destructive">{reason}</p>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={retrying}
        onClick={() => onRetry(documentId)}
        className="shrink-0"
      >
        <RotateCcw className="size-3" aria-hidden="true" />
        {retrying ? 'Retrying…' : 'Retry'}
      </Button>
    </li>
  );
}

function WebsiteKnowledgeDetail({ websiteId }: { websiteId: string }) {
  const { data, isPending, isError, error } = useKnowledgeDocuments(websiteId);
  const retry = useRetryDocument(websiteId);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());

  if (isPending) {
    return (
      <div className="space-y-2" aria-label="Loading document status">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error?.message ?? 'Failed to load document status.'}
      </p>
    );
  }

  const failed = data.documents.filter((document) => document.status === 'failed');

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

  return (
    <div className="space-y-3" data-testid="website-knowledge-detail">
      <ProcessingProgress summary={data.summary} />
      <DocumentSummary summary={data.summary} />

      {failed.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Failed documents
          </p>
          <ul className="flex flex-col gap-2">
            {failed.map((document) => (
              <FailedDocument
                key={document.id}
                documentId={document.id}
                url={document.url}
                reason={document.failure_reason ?? 'Unknown error'}
                onRetry={(id) => void handleRetry(id)}
                retrying={retryingIds.has(document.id)}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function WebsiteRow({
  website,
}: {
  website: { id: string; name: string; url: string; knowledge_status: KnowledgeStatus };
}) {
  const [open, setOpen] = useState(false);

  return (
    <li className="py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Database className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <Link href="/websites" className="truncate font-medium hover:underline">
              {website.name}
            </Link>
            <KnowledgeBadge status={website.knowledge_status} />
          </div>
          <a
            href={website.url}
            target="_blank"
            rel="noreferrer"
            className="mt-0.5 inline-flex items-center gap-1 truncate text-sm text-muted-foreground hover:text-foreground"
          >
            <span className="truncate">{website.url}</span>
            <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
          </a>
        </div>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
          >
            {open ? 'Hide documents' : 'Documents'}
          </Button>
        </div>
      </div>
      {open ? (
        <div className="mt-3 rounded-lg border bg-muted/20 p-4">
          <WebsiteKnowledgeDetail websiteId={website.id} />
        </div>
      ) : null}
    </li>
  );
}

export function KnowledgePage() {
  const router = useRouter();
  const { data, isPending, isError, error, refetch } = useWebsites();

  const websites = data ?? [];
  const totalChunks = websites.reduce((sum, site) => sum + site.knowledge_chunks, 0);
  const totalDocuments = websites.reduce((sum, site) => sum + site.knowledge_documents, 0);
  const readySites = websites.filter((site) => site.knowledge_status === 'ready').length;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Knowledge Base"
        description="Content extracted from your websites and embedded for retrieval."
      />

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((index) => (
            <Card key={index}>
              <CardHeader>
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load knowledge base.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <KnowledgeStat label="Total chunks" value={totalChunks} />
            <KnowledgeStat label="Documents embedded" value={totalDocuments} />
            <KnowledgeStat label="Websites ready" value={readySites} />
          </div>

          {websites.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center gap-6 py-12 text-center">
                <div className="flex flex-col items-center gap-2">
                  <h3 className="text-lg font-semibold">Build your knowledge base</h3>
                  <p className="max-w-md text-sm text-muted-foreground">
                    Your AI assistant learns from your website content. Add a website and run a
                    crawl to get started.
                  </p>
                </div>

                <ol className="flex w-full max-w-md flex-col gap-3 text-left">
                  {[
                    {
                      step: 1,
                      label: 'Add your website URL',
                      desc: 'Tell us which site to index.',
                    },
                    {
                      step: 2,
                      label: 'Crawl to extract content',
                      desc: 'We fetch pages and extract text automatically.',
                    },
                    {
                      step: 3,
                      label: 'AI learns from your content',
                      desc: 'Chunks are embedded so your assistant can answer questions.',
                    },
                  ].map(({ step, label, desc }) => (
                    <li key={step} className="flex items-start gap-3">
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                        {step}
                      </span>
                      <div>
                        <p className="text-sm font-medium">{label}</p>
                        <p className="text-xs text-muted-foreground">{desc}</p>
                      </div>
                    </li>
                  ))}
                </ol>

                <Button onClick={() => router.push('/websites')}>Add your first website</Button>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Websites</CardTitle>
                <CardDescription>
                  Embedding status per website. Open a website to see per-document progress and
                  failed pages.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col divide-y">
                  {websites.map((website) => (
                    <WebsiteRow key={website.id} website={website} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </>
      ) : null}
    </div>
  );
}
