'use client';

import Link from 'next/link';
import { Brain, Loader2 } from 'lucide-react';

import { useKnowledgeReadinessForSites } from '@/features/knowledge/hooks';
import { useWebsites } from '@/features/websites/hooks';
import { isEmbeddingInProgress } from '@/features/websites/types';

export function CrawlStatusBanner() {
  const { data } = useWebsites();
  const sites = data ?? [];
  const crawling = sites.filter((s) => s.status === 'crawling');

  // Per-document derived readiness: a site is only "embedding" while any
  // document is pending/processing/rate-limited, even if the persisted
  // `knowledge_status` was already flipped to `ready` prematurely. The legacy
  // `isEmbeddingInProgress` fallback covers the brief window while the
  // /documents data is still being fetched for a genuinely-processing site.
  const readinessForSites = useKnowledgeReadinessForSites(sites);
  const embedding = readinessForSites.filter(
    ({ site, readiness }) => readiness.isEmbedding || isEmbeddingInProgress(site),
  );

  if (crawling.length === 0 && embedding.length === 0) return null;

  const names = crawling.map((s) => s.name);
  const label =
    names.length === 1
      ? `Crawling ${names[0]}…`
      : `Crawling ${names[0]} + ${names.length - 1} other site${names.length > 2 ? 's' : ''}…`;

  const embeddingNames = embedding.map(({ site }) => site.name);
  const embeddingLabel =
    embeddingNames.length === 1
      ? `Generating embeddings for ${embeddingNames[0]}…`
      : `Generating embeddings for ${embeddingNames[0]} + ${embeddingNames.length - 1} other site${
          embeddingNames.length > 2 ? 's' : ''
        }…`;

  return (
    <>
      {crawling.length > 0 ? (
        <div className="border-b border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200">
          <Link
            href="/websites"
            className="flex min-w-0 items-center gap-2 font-medium hover:underline"
          >
            <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden="true" />
            <span className="min-w-0 truncate">{label}</span>
          </Link>
        </div>
      ) : null}

      {embedding.length > 0 ? (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <Link
            href="/websites"
            className="flex min-w-0 items-center gap-2 font-medium hover:underline"
          >
            <Brain className="size-3.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0 truncate">{embeddingLabel}</span>
          </Link>
        </div>
      ) : null}
    </>
  );
}
