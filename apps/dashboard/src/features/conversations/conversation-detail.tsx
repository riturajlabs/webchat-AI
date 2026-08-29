'use client';

import { useState } from 'react';
import { ArrowLeft, Bot, Clock, Trash2, User } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/error-state';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';
import { ConfirmDialog } from '@/features/admin/confirm-dialog';

import { useWebsites } from '@/features/websites/hooks';

import { formatDateTime, formatResponseTime, visitorLabel } from './format';
import { useConversation, useDeleteConversation } from './hooks';
import { ConversationStatusBadge } from './status-badge';
import type { ConversationMessage } from './types';

function MessageSources({ sources }: { sources: ConversationMessage['sources'] }) {
  if (sources.length === 0) {
    return null;
  }
  return (
    <div className="mt-1 flex flex-col gap-1.5 border-t pt-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">Sources</p>
      <ol className="flex flex-col gap-1">
        {sources.map((source) => (
          <li key={`${source.citation}-${source.url}`} className="text-sm">
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex max-w-full items-center gap-1.5 text-blue-600 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:text-blue-400"
            >
              <span
                aria-hidden="true"
                className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-xs font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300"
              >
                [{source.citation}]
              </span>
              <span className="truncate">{source.title || source.url}</span>
            </a>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Chat-style transcript rows: visitor messages sit right-aligned on a neutral
 * surface, assistant messages left-aligned with source citations (blue links).
 */
function MessageBubble({ message }: { message: ConversationMessage }) {
  const isUser = message.role === 'user';
  return (
    <article
      aria-label={`${isUser ? 'Visitor' : 'Assistant'} message`}
      className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}
    >
      <div
        className={cn(
          'flex max-w-[85%] flex-col gap-2 rounded-2xl p-4',
          isUser
            ? 'rounded-br-md bg-secondary text-secondary-foreground'
            : 'rounded-bl-md border bg-card shadow-sm',
        )}
      >
        <div
          className={cn(
            'flex items-center gap-2 text-xs font-medium',
            isUser ? 'text-muted-foreground' : 'text-blue-600 dark:text-blue-400',
          )}
        >
          {isUser ? (
            <User className="size-3.5" aria-hidden="true" />
          ) : (
            <Bot className="size-3.5" aria-hidden="true" />
          )}
          <span>{isUser ? 'Visitor' : 'Assistant'}</span>
          <time dateTime={message.created_at} className="font-normal text-muted-foreground">
            {formatDateTime(message.created_at)}
          </time>
        </div>

        <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>

        {!isUser ? (
          <>
            <MessageSources sources={message.sources} />
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="size-3.5" aria-hidden="true" />
              {message.input_tokens} in / {message.output_tokens} out tokens ·{' '}
              {formatResponseTime(message.response_time)}
            </p>
          </>
        ) : null}
      </div>
    </article>
  );
}

export function ConversationDetailPage({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const { data, isPending, isError, error, refetch } = useConversation(sessionId);
  const deleteConversation = useDeleteConversation();
  const { data: websitesData } = useWebsites();
  const websiteName = (websitesData ?? []).find((website) => website.id === data?.website_id)?.name;
  const [confirmOpen, setConfirmOpen] = useState(false);

  const notFound = error instanceof ApiError && error.status === 404;

  async function confirmDelete() {
    try {
      await deleteConversation.mutateAsync(sessionId);
      toast.success('Conversation deleted');
      router.replace('/conversations');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete conversation.');
    } finally {
      setConfirmOpen(false);
    }
  }

  if (isPending) {
    return (
      <div role="status" aria-label="Loading conversation" className="flex flex-col gap-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError) {
    if (notFound) {
      return (
        <div className="flex flex-col items-center gap-4 rounded-lg border border-dashed p-10 text-center">
          <p className="font-medium">Conversation not found</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            It may have been deleted or you don&apos;t have access to it.
          </p>
          <Button variant="outline" asChild>
            <Link href="/conversations">
              <ArrowLeft aria-hidden="true" />
              Back to conversations
            </Link>
          </Button>
        </div>
      );
    }
    return (
      <ErrorState
        message={error?.message ?? 'Failed to load conversation.'}
        onRetry={() => void refetch()}
      />
    );
  }

  if (!data) {
    return null;
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-4 border-b pb-6">
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 self-start text-muted-foreground"
          asChild
        >
          <Link href="/conversations">
            <ArrowLeft aria-hidden="true" />
            Conversations
          </Link>
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="truncate font-sans text-2xl font-bold tracking-tight">{data.title}</h1>
              <ConversationStatusBadge status={data.status} />
            </div>
            <dl className="flex flex-wrap gap-x-8 gap-y-2">
              <div className="flex flex-col">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Visitor</dt>
                <dd className="text-sm font-medium">{visitorLabel(data.visitor_id)}</dd>
              </div>
              {websiteName ? (
                <div className="flex flex-col">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Website</dt>
                  <dd className="text-sm font-medium">{websiteName}</dd>
                </div>
              ) : null}
              <div className="flex flex-col">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Started</dt>
                <dd className="text-sm font-medium">{formatDateTime(data.created_at)}</dd>
              </div>
              <div className="flex flex-col">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  Last activity
                </dt>
                <dd className="text-sm font-medium">{formatDateTime(data.updated_at)}</dd>
              </div>
            </dl>
          </div>
          <Button variant="destructive" size="sm" onClick={() => setConfirmOpen(true)}>
            <Trash2 aria-hidden="true" />
            Delete
          </Button>
        </div>
      </header>

      <section aria-labelledby="conversation-messages-heading" className="flex flex-col gap-4">
        <h2 id="conversation-messages-heading" className="sr-only">
          Messages
        </h2>
        <ol className="flex flex-col gap-4">
          {data.messages.map((message, index) => (
            <li key={`${message.role}-${index}`}>
              <MessageBubble message={message} />
            </li>
          ))}
        </ol>
      </section>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onConfirm={() => void confirmDelete()}
        title="Delete conversation"
        description="Delete this conversation and its entire history?"
        confirmLabel="Delete"
        variant="destructive"
        isPending={deleteConversation.isPending}
      />
    </div>
  );
}
