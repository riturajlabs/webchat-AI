'use client';

import Link from 'next/link';
import { Loader2 } from 'lucide-react';

import { useWebsites } from '@/features/websites/hooks';

export function CrawlStatusBanner() {
  const { data } = useWebsites();
  const sites = data ?? [];
  const crawling = sites.filter((s) => s.status === 'crawling');

  if (crawling.length === 0) return null;

  const names = crawling.map((s) => s.name);
  const label =
    names.length === 1
      ? `Crawling ${names[0]}…`
      : `Crawling ${names[0]} + ${names.length - 1} other site${names.length > 2 ? 's' : ''}…`;

  return (
    <div className="border-b border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200">
      <Link
        href="/websites"
        className="flex min-w-0 items-center gap-2 font-medium hover:underline"
      >
        <Loader2 className="size-3.5 shrink-0 animate-spin" aria-hidden="true" />
        <span className="min-w-0 truncate">{label}</span>
      </Link>
    </div>
  );
}
