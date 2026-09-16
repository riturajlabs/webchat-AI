'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronDown, Database, ExternalLink, Upload } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { useWebsites } from '@/features/websites/hooks';
import { KnowledgeBadge } from '@/features/websites/knowledge-badge';

import { DocumentProgressPanel } from './document-progress-panel';
import { useKnowledgeReadinessForSites } from './hooks';
import type { KnowledgeReadiness } from './status';
import { UploadKnowledgeDialog } from './upload-modal';

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

interface WebsiteRowProps {
  website: { id: string; name: string; url: string | null };
  readiness: KnowledgeReadiness;
}

function WebsiteRow({ website, readiness }: WebsiteRowProps) {
  const [open, setOpen] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const panelId = `website-docs-${website.id}`;

  return (
    <li className="py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <Database className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <Link href="/websites" className="min-w-0 truncate font-medium hover:underline">
              {website.name}
            </Link>
            <KnowledgeBadge status={readiness.status} embedding={readiness.isEmbedding} />
          </div>
          {website.url ? (
            <a
              href={website.url}
              target="_blank"
              rel="noreferrer"
              className="mt-0.5 inline-flex max-w-full items-center gap-1 truncate text-sm text-muted-foreground hover:text-foreground"
            >
              <span className="min-w-0 truncate">{website.url}</span>
              <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
            </a>
          ) : (
            <span className="mt-0.5 block text-xs text-muted-foreground">Document chatbot</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5 text-xs font-medium"
            onClick={() => setUploadOpen(true)}
          >
            <Upload className="size-3.5 shrink-0" aria-hidden="true" />
            <span>Upload files</span>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5 text-xs font-medium"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls={panelId}
          >
            <span>{open ? 'Hide documents' : 'Show documents'}</span>
            <ChevronDown
              className={`size-3.5 shrink-0 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
              aria-hidden="true"
            />
          </Button>
        </div>
      </div>
      <UploadKnowledgeDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        websiteId={website.id}
        websiteName={website.name}
      />
      {open ? (
        <div
          id={panelId}
          role="region"
          aria-label={`Documents for ${website.name}`}
          className="mt-3 rounded-lg border bg-muted/20 p-4"
        >
          <DocumentProgressPanel websiteId={website.id} />
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

  // Per-document derived readiness for every website. A site only counts as
  // "ready" when its documents confirm the pipeline drained — the backend's
  // persisted `knowledge_status` can be `ready` while siblings still embed.
  const readinessBySite = useKnowledgeReadinessForSites(websites);
  const readySites = readinessBySite.filter(({ readiness }) => readiness.isReady).length;

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
                  Embedding status per website. Open a website to see per-page progress for every
                  document — including pages still pending, being processed, awaiting a deferred
                  retry, and failed pages with their error details.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col divide-y">
                  {readinessBySite.map(({ site, readiness }) => (
                    <WebsiteRow key={site.id} website={site} readiness={readiness} />
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
