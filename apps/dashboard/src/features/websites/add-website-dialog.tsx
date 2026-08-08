'use client';

import { useState, type FormEvent } from 'react';
import { Check, Copy, X } from 'lucide-react';

import { Button } from '@/components/ui/button';

import { useCreateWebsite, useUpdateWebsite } from './hooks';
import type { CreateWebsiteResponse, Website } from './types';

export function AddWebsiteDialog({
  open,
  onOpenChange,
  website,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set, the dialog edits this website instead of creating one. */
  website?: Website | null;
}) {
  const createWebsite = useCreateWebsite();
  const updateWebsite = useUpdateWebsite();
  const isEditing = Boolean(website);

  const [name, setName] = useState(website?.name ?? '');
  const [url, setUrl] = useState(website?.url ?? '');
  const [result, setResult] = useState<CreateWebsiteResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const isPending = createWebsite.isPending || updateWebsite.isPending;
  const error = createWebsite.error ?? updateWebsite.error;

  function close() {
    onOpenChange(false);
    setName('');
    setUrl('');
    setResult(null);
    setCopied(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !url.trim() || isPending) {
      return;
    }
    try {
      if (isEditing && website) {
        await updateWebsite.mutateAsync({
          websiteId: website.id,
          name: name.trim(),
          url: url.trim(),
        });
        close();
      } else {
        const created = await createWebsite.mutateAsync({ name: name.trim(), url: url.trim() });
        setResult(created);
      }
    } catch {
      // The mutation error is already surfaced via the mutation state.
    }
  }

  async function copyEmbed() {
    if (!result) {
      return;
    }
    try {
      await navigator.clipboard.writeText(result.embed_script);
      setCopied(true);
    } catch {
      setCopied(false);
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
      aria-labelledby="add-website-title"
    >
      <div className="absolute inset-0 bg-black/50" onClick={close} aria-hidden="true" />
      <div className="relative z-10 w-full max-w-md rounded-lg border bg-background p-6 shadow-lg">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="add-website-title" className="font-sans text-lg font-semibold">
              {isEditing ? 'Edit website' : 'Add website'}
            </h2>
            <p className="text-sm text-muted-foreground">
              {isEditing
                ? 'Update the site details below.'
                : 'Connect a website to build its AI assistant.'}
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
              <p className="font-medium text-green-900">Website added</p>
              <p className="text-green-800">
                Your widget is ready. Save the secret below - it is shown only once.
              </p>
            </div>

            <div>
              <label
                htmlFor="widget-secret"
                className="mb-1 block text-xs font-medium text-muted-foreground"
              >
                Widget secret (one-time)
              </label>
              <code
                id="widget-secret"
                className="block break-all rounded-md bg-muted p-2 font-mono text-xs"
              >
                {result.widget_secret}
              </code>
            </div>

            <div>
              <label
                htmlFor="embed-script"
                className="mb-1 block text-xs font-medium text-muted-foreground"
              >
                Embed script
              </label>
              <textarea
                id="embed-script"
                readOnly
                value={result.embed_script}
                rows={3}
                className="w-full resize-none rounded-md border bg-muted p-2 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void copyEmbed()}
              >
                {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copied ? 'Copied' : 'Copy embed code'}
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
                htmlFor="website-name"
                className="mb-1 block text-xs font-medium text-muted-foreground"
              >
                Name
              </label>
              <input
                id="website-name"
                required
                minLength={2}
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Acme Inc"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              />
            </div>

            <div>
              <label
                htmlFor="website-url"
                className="mb-1 block text-xs font-medium text-muted-foreground"
              >
                Website URL
              </label>
              <input
                id="website-url"
                required
                type="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://example.com"
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
              <Button type="submit" disabled={isPending}>
                {isPending ? 'Saving…' : isEditing ? 'Save changes' : 'Add website'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
