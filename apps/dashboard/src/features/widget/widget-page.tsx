'use client';

import { useState } from 'react';
import { Check, Copy, Puzzle } from 'lucide-react';

import { useWebsites, useWebsiteWidget } from '@/features/websites/hooks';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className={mono ? 'mt-0.5 truncate font-mono text-sm' : 'mt-0.5 text-sm'}>
        {value || '—'}
      </dd>
    </div>
  );
}

function BoolField({ label, value }: { label: string; value: boolean }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{value ? 'Yes' : 'No'}</dd>
    </div>
  );
}

export function WidgetPage() {
  const { data: websites, isPending, isError, error, refetch } = useWebsites();
  const [selectedId, setSelectedId] = useState<string>('');

  const selected = selectedId || websites?.[0]?.id || null;
  const {
    data: widgetData,
    isPending: widgetPending,
    isError: widgetError,
  } = useWebsiteWidget(selected);

  const [copied, setCopied] = useState(false);

  async function copyEmbed() {
    if (!widgetData) {
      return;
    }
    try {
      await navigator.clipboard.writeText(widgetData.embed_script);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Widget</h1>
        <p className="text-sm text-muted-foreground">
          Preview your assistant widget and copy the embed script.
        </p>
      </div>

      {isPending ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-10 w-full max-w-xs" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}

      {isError ? (
        <div
          role="alert"
          className="flex flex-col items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm text-destructive">{error?.message ?? 'Failed to load websites.'}</p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {!isPending && !isError && (!websites || websites.length === 0) ? (
        <EmptyState
          title="No widget yet"
          description="Add a website first — its widget is created automatically."
        />
      ) : null}

      {!isPending && !isError && websites && websites.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Widget settings</CardTitle>
            <CardDescription>
              Widget customization API will be available in a future phase.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="widget-website">Website</Label>
              <select
                id="widget-website"
                value={selectedId || websites[0].id}
                onChange={(event) => {
                  setSelectedId(event.target.value);
                  setCopied(false);
                }}
                className="flex h-9 w-full max-w-xs rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {websites.map((website) => (
                  <option key={website.id} value={website.id}>
                    {website.name}
                  </option>
                ))}
              </select>
            </div>

            {widgetPending ? (
              <div className="flex flex-col gap-4">
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-24 w-full" />
              </div>
            ) : null}

            {widgetError ? (
              <div
                role="alert"
                className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
              >
                Failed to load the widget configuration.
              </div>
            ) : null}

            {widgetData ? (
              <>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
                  <Field label="Widget ID" value={widgetData.widget.widget_id} mono />
                  <Field label="Theme" value={widgetData.widget.theme} />
                  <Field label="Position" value={widgetData.widget.position} />
                  <div>
                    <dt className="text-sm text-muted-foreground">Primary color</dt>
                    <dd className="mt-0.5 flex items-center gap-2 text-sm">
                      <span
                        className="inline-block size-3 rounded-full border"
                        style={{ backgroundColor: widgetData.widget.primary_color }}
                        aria-hidden="true"
                      />
                      {widgetData.widget.primary_color}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-muted-foreground">Accent color</dt>
                    <dd className="mt-0.5 flex items-center gap-2 text-sm">
                      <span
                        className="inline-block size-3 rounded-full border"
                        style={{ backgroundColor: widgetData.widget.accent_color }}
                        aria-hidden="true"
                      />
                      {widgetData.widget.accent_color}
                    </dd>
                  </div>
                  <Field label="Font size" value={widgetData.widget.font_size} />
                  <Field label="Welcome message" value={widgetData.widget.welcome_message} />
                  <Field label="Placeholder" value={widgetData.widget.placeholder} />
                  <Field
                    label="Suggested questions"
                    value={widgetData.widget.suggested_questions.join(', ')}
                  />
                  <BoolField label="Branding" value={widgetData.widget.branding} />
                  <BoolField label="Dark mode" value={widgetData.widget.dark_mode} />
                  <BoolField label="Auto open" value={widgetData.widget.auto_open} />
                  <BoolField label="Enabled" value={widgetData.widget.enabled} />
                </dl>

                <div className="rounded-md border bg-muted/40 p-3">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Embed script</p>
                  <pre className="overflow-x-auto rounded-md bg-background p-3 font-mono text-xs">
                    {widgetData.embed_script}
                  </pre>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={() => void copyEmbed()}
                  >
                    {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                    {copied ? 'Copied' : 'Copy embed code'}
                  </Button>
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {!isPending && !isError && websites && websites.length > 0 ? (
        <div role="note" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Puzzle className="size-4" aria-hidden="true" />
          Widget customization API will be available in a future phase.
        </div>
      ) : null}
    </div>
  );
}
