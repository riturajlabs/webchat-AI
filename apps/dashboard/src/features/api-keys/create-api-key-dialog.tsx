'use client';

import { useState, type FormEvent } from 'react';
import { Check, Copy, X } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';

import { useCreateApiKey } from './hooks';
import type { CreateApiKeyResponse } from './types';

export function CreateApiKeyDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const createApiKey = useCreateApiKey();

  const [name, setName] = useState('');
  const [result, setResult] = useState<CreateApiKeyResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const error = createApiKey.error;

  function close() {
    onOpenChange(false);
    setName('');
    setResult(null);
    setCopied(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || createApiKey.isPending) {
      return;
    }
    try {
      const created = await createApiKey.mutateAsync({ name: name.trim() });
      setResult(created);
      toast.success('API key created');
    } catch {
      toast.error('Failed to create API key');
      // The mutation error is already surfaced via the mutation state.
    }
  }

  async function copyKey() {
    if (!result) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.api_key);
      setCopied(true);
      toast.success('API key copied to clipboard');
    } catch {
      setCopied(false);
      toast.error('Failed to copy API key');
    }
  }

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-api-key-title"
    >
      <div className="absolute inset-0 bg-black/50" onClick={close} aria-hidden="true" />
      <div className="relative z-10 w-full max-w-md rounded-lg border bg-background p-6 shadow-lg">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="create-api-key-title" className="font-sans text-lg font-semibold">
              Create API key
            </h2>
            <p className="text-sm text-muted-foreground">
              {result
                ? 'Save the secret now - it is shown only once.'
                : 'Name a key for your integration.'}
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={close} aria-label="Close dialog">
            <X aria-hidden="true" />
          </Button>
        </div>

        {result ? (
          <div className="flex flex-col gap-4">
            <div
              role="status"
              className="rounded-md border border-green-200 bg-green-50 p-3 text-sm"
            >
              <p className="font-medium text-green-900">API key created</p>
              <p className="text-green-800">Copy it now - you will not be able to see it again.</p>
            </div>

            <div>
              <label
                htmlFor="api-key-secret"
                className="mb-1 block text-xs font-medium text-muted-foreground"
              >
                API key (one-time)
              </label>
              <code
                id="api-key-secret"
                className="block break-all rounded-md bg-muted p-2 font-mono text-xs"
              >
                {result.api_key}
              </code>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void copyKey()}
              >
                {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copied ? 'Copied' : 'Copy API key'}
              </Button>
            </div>

            <Button type="button" onClick={close} className="mt-2">
              Done
            </Button>
          </div>
        ) : (
          <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
            <div>
              <label
                htmlFor="api-key-name"
                className="mb-1 block text-xs font-medium text-muted-foreground"
              >
                Name
              </label>
              <input
                id="api-key-name"
                required
                minLength={2}
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Production"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              />
            </div>

            {error ? (
              <p
                role="alert"
                className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {error.message}
              </p>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button type="submit" disabled={createApiKey.isPending}>
                {createApiKey.isPending ? 'Creating…' : 'Create API key'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
