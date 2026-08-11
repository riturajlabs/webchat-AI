'use client';

import { ArrowLeft, BookOpen, Clock, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/utils';

import { useWebsites } from '@/features/websites/hooks';

import { formatDateTime, formatResponseTime, visitorLabel } from './format';
import { useConversation, useDeleteConversation } from './hooks';
import { ConversationStatusBadge } from './status-badge';
import type { ConversationMessage } from './types';

function MessageBubble({ message }: { message: ConversationMessage }) {
  const isUser = message.role === 'user';
  return (
    <article
      className={cn(
        'flex flex-col gap-2 rounded-lg border p-4 shadow-sm',
        isUser ? 'bg-primary/5' : 'bg-card',
      )}
    >
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>

      {!isUser && message.sources.length > 0 ? (
        <div className="mt-1 flex flex-col gap-1.5 border-t pt-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <BookOpen className="size-3.5" aria-hidden="true" />
            Sources
          </p>
          <ul className="flex flex-col gap-1">
            {message.sources.map((source) => (
              <li key={`${source.citation}-${source.url}`} className="text-sm">
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {source.title || source.url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!isUser ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="size-3.5" aria-hidden="true" />
          {message.input_tokens} in / {message.output_tokens} out tokens ·{' '}
          {formatResponseTime(message.response_time)}
        </p>
      ) : null}
    </article>
  );
}

export function ConversationDetailPage({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const { data, isPending, isError, error, refetch } = useConversation(sessionId);
  const deleteConversation = useDeleteConversation();
  const { data: websitesData } = useWebsites();
  const websiteName = (websitesData ?? []).find((website) => website.id === data?.website_id)?.name;

  const notFound = error instanceof ApiError && error.status === 404;

  async function handleDelete() {
    if (!window.confirm('Delete this conversation and its entire history?')) {
      return;
    }
    try {
      await deleteConversation.mutateAsync(sessionId);
      toast.success('Conversation deleted');
      router.replace('/conversations');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete conversation.');
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
      <div
        role="alert"
        className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
      >
        <p className="text-sm text-destructive">
          {error?.message ?? 'Failed to load conversation.'}
        </p>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-2">
          <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" asChild>
            <Link href="/conversations">
              <ArrowLeft aria-hidden="true" />
              Conversations
            </Link>
          </Button>
          <h1 className="font-sans text-2xl font-bold tracking-tight">{data.title}</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>{visitorLabel(data.visitor_id)}</span>
            {websiteName ? <span>{websiteName}</span> : null}
            <span>Started {formatDateTime(data.created_at)}</span>
            <span>Updated {formatDateTime(data.updated_at)}</span>
            <ConversationStatusBadge status={data.status} />
          </div>
        </div>
        <Button variant="destructive" size="sm" onClick={() => void handleDelete()}>
          <Trash2 aria-hidden="true" />
          Delete
        </Button>
      </div>

      <ol className="flex flex-col gap-3">
        {data.messages.map((message, index) => (
          <li key={`${message.created_at}-${index}`}>
            <MessageBubble message={message} />
          </li>
        ))}
      </ol>
    </div>
  );
}
