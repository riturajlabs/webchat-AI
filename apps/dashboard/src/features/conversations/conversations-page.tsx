'use client';

import { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { MessagesSquare } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Conversations</h1>
        <p className="text-sm text-muted-foreground">
          Chat history and per-assistant conversation threads.
        </p>
      </div>

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
            <div key={index} className="h-16 rounded-lg border bg-card p-4 shadow-sm">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="mt-2 h-3 w-64" />
            </div>
          ))}
        </div>
      ) : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">
            {error?.message ?? 'Failed to load conversations.'}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
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
          <EmptyState
            icon={MessagesSquare}
            title="No conversations yet"
            description="Chats from your widget and dashboard will appear here."
          />
        )
      ) : null}

      {!isPending && !isError && conversations.length > 0 ? (
        <>
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
