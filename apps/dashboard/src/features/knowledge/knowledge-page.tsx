'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Database, ExternalLink } from 'lucide-react';

import { useWebsites } from '@/features/websites/hooks';
import type { KnowledgeStatus } from '@/features/websites/types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

const KNOWLEDGE_STYLES: Record<KnowledgeStatus, string> = {
  none: 'bg-muted text-muted-foreground',
  processing: 'bg-amber-100 text-amber-800',
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

function KnowledgeBadge({ status }: { status: KnowledgeStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize',
        KNOWLEDGE_STYLES[status],
      )}
    >
      {status}
    </span>
  );
}

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

export function KnowledgePage() {
  const router = useRouter();
  const { data, isPending, isError, error, refetch } = useWebsites();

  const websites = data ?? [];
  const totalChunks = websites.reduce((sum, site) => sum + site.knowledge_chunks, 0);
  const totalDocuments = websites.reduce((sum, site) => sum + site.knowledge_documents, 0);
  const readySites = websites.filter((site) => site.knowledge_status === 'ready').length;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Knowledge Base</h1>
        <p className="text-sm text-muted-foreground">
          Content extracted from your websites and embedded for retrieval.
        </p>
      </div>

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
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">
            {error?.message ?? 'Failed to load knowledge base.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <KnowledgeStat label="Total chunks" value={totalChunks} />
            <KnowledgeStat label="Documents embedded" value={totalDocuments} />
            <KnowledgeStat label="Websites ready" value={readySites} />
          </div>

          {websites.length === 0 ? (
            <EmptyState
              title="No knowledge yet"
              description="Add a website and run a crawl to start building its knowledge base."
              actionLabel="Go to websites"
              onAction={() => router.push('/websites')}
            />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Websites</CardTitle>
                <CardDescription>Embedding and retrieval status per website.</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col divide-y">
                  {websites.map((website) => (
                    <li key={website.id} className="flex items-center justify-between gap-4 py-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <Database
                            className="size-4 shrink-0 text-muted-foreground"
                            aria-hidden="true"
                          />
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
                      <dl className="hidden text-right text-xs sm:block">
                        <div className="flex gap-6">
                          <div>
                            <dt className="text-muted-foreground">Chunks</dt>
                            <dd className="font-medium">{website.knowledge_chunks}</dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Documents</dt>
                            <dd className="font-medium">{website.knowledge_documents}</dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">Last updated</dt>
                            <dd className="font-medium">{formatDate(website.last_knowledge_at)}</dd>
                          </div>
                        </div>
                      </dl>
                    </li>
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
