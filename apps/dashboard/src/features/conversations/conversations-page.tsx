'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { FlaskConical, MessagesSquare, Puzzle, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';

import { useWebsites } from '@/features/websites/hooks';

import { ConversationListItem } from './conversation-list-item';
import { useConversations } from './hooks';

const DEFAULT_PER_PAGE = 20;
const SEARCH_DEBOUNCE_MS = 300;

export function ConversationsPage() {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [websiteId, setWebsiteId] = useState('');

  const { data: websitesData } = useWebsites();
  const { data, isPending, isError, error, refetch } = useConversations({
    page,
    perPage: DEFAULT_PER_PAGE,
    search: search || undefined,
    websiteId: websiteId || undefined,
  });

  const websiteNames = useMemo(
    () => new Map((websitesData ?? []).map((website) => [website.id, website.name])),
    [websitesData],
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const conversations = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / DEFAULT_PER_PAGE));
  const hasFilters = Boolean(search || websiteId);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Conversations"
        description="Review customer conversations with your AI assistant."
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <Label htmlFor="conversation-search" className="sr-only">
            Search conversations
          </Label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id="conversation-search"
              type="search"
              placeholder="Search conversations…"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              className="pl-9"
            />
          </div>
        </div>
        <div className="sm:w-56">
          <Label htmlFor="website-filter" className="sr-only">
            Filter by website
          </Label>
          <select
            id="website-filter"
            value={websiteId}
            onChange={(event) => {
              setWebsiteId(event.target.value);
              setPage(1);
            }}
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <option value="">All websites</option>
            {(websitesData ?? []).map((website) => (
              <option key={website.id} value={website.id}>
                {website.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isPending ? (
        <div role="status" aria-label="Loading conversations" className="flex flex-col gap-3">
          {[0, 1, 2, 3].map((index) => (
            <div
              key={index}
              className="flex flex-col gap-2 rounded-lg border bg-card p-4 shadow-sm"
            >
              <div className="flex items-center justify-between">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-5 w-20 rounded-full" />
              </div>
              <Skeleton className="h-3 w-64" />
              <Skeleton className="h-3 w-48" />
            </div>
          ))}
        </div>
      ) : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load conversations.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError && conversations.length === 0 ? (
        hasFilters ? (
          <EmptyState
            icon={MessagesSquare}
            title="No matching conversations"
            description="Try a different search term or website filter."
            actionLabel="Clear filters"
            onAction={() => {
              setSearchInput('');
              setSearch('');
              setWebsiteId('');
              setPage(1);
            }}
          />
        ) : (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-10 text-center">
            <MessagesSquare className="size-8 text-muted-foreground/50" aria-hidden="true" />
            <p className="font-medium">No conversations yet</p>
            <p className="max-w-sm text-sm text-muted-foreground">
              Install your widget and start receiving customer questions.
            </p>
            <div className="mt-1 flex flex-wrap justify-center gap-2">
              <Button asChild>
                <Link href="/widget">
                  <Puzzle aria-hidden="true" />
                  Install your widget
                </Link>
              </Button>
              <Button variant="outline" asChild>
                <Link href="/widget-test">
                  <FlaskConical aria-hidden="true" />
                  Widget Test
                </Link>
              </Button>
            </div>
          </div>
        )
      ) : null}

      {!isPending && !isError && conversations.length > 0 ? (
        <>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {data?.total ?? 0} {data?.total === 1 ? 'conversation' : 'conversations'}
            {search ? ` matching “${search}”` : ''}
          </p>
          <ul className="flex flex-col gap-3">
            {conversations.map((item) => (
              <ConversationListItem
                key={item.id}
                item={item}
                websiteName={websiteNames.get(item.website_id)}
              />
            ))}
          </ul>

          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              Page {data?.page ?? 1} of {totalPages}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
