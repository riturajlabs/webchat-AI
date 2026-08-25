'use client';

import { useState } from 'react';
import { KeyRound, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';

import { CreateApiKeyDialog } from './create-api-key-dialog';
import { useApiKeys, useRevokeApiKey } from './hooks';
import type { ApiKey } from './types';

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { timeZone: 'UTC' });
}

export function ApiKeysPage() {
  const { data, isPending, isError, error, refetch } = useApiKeys();
  const revokeApiKey = useRevokeApiKey();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingKeyId, setPendingKeyId] = useState<string | null>(null);

  const apiKeys = data ?? [];

  async function handleRevoke(key: ApiKey) {
    if (!window.confirm(`Revoke "${key.name}"? This immediately disables the key.`)) {
      return;
    }
    setPendingKeyId(key.id);
    try {
      await revokeApiKey.mutateAsync(key.id);
      toast.success(`Revoked "${key.name}"`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to revoke API key.');
    } finally {
      setPendingKeyId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="API Keys"
        description="Manage programmatic access to your assistants."
        actions={
          <Button onClick={() => setDialogOpen(true)}>
            <Plus aria-hidden="true" />
            Create API key
          </Button>
        }
      />

      {isPending ? (
        <div role="status" aria-label="Loading API keys" className="flex flex-col gap-3">
          {[0, 1].map((index) => (
            <div
              key={index}
              className="flex items-center justify-between gap-4 rounded-lg border bg-card p-4 shadow-sm"
            >
              <div className="flex-1 space-y-2">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-4 w-64" />
              </div>
              <Skeleton className="h-8 w-16" />
            </div>
          ))}
        </div>
      ) : null}

      {isError ? (
        <ErrorState
          message={error?.message ?? 'Failed to load API keys.'}
          onRetry={() => void refetch()}
        />
      ) : null}

      {!isPending && !isError && apiKeys.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          title="No API keys yet"
          description="Create a key to authenticate programmatic requests to your assistants."
          actionLabel="Create your first API key"
          onAction={() => setDialogOpen(true)}
        />
      ) : null}

      {!isPending && !isError && apiKeys.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {apiKeys.map((key) => (
            <li
              key={key.id}
              className="flex flex-wrap items-center justify-between gap-4 rounded-lg border bg-card p-4 shadow-sm"
            >
              <div className="min-w-0">
                <p className="font-medium">{key.name}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {key.key_prefix}
                  {'\u2022'.repeat(24)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Created {formatDate(key.created_at)}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={pendingKeyId === key.id}
                onClick={() => void handleRevoke(key)}
              >
                <Trash2 aria-hidden="true" />
                {pendingKeyId === key.id ? 'Revoking…' : 'Revoke'}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <CreateApiKeyDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
