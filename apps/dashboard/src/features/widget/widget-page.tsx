'use client';

import { useState } from 'react';
import { Puzzle } from 'lucide-react';

import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { useWebsites } from '@/features/websites/hooks';

import { WidgetEditor } from './components/widget-editor';
import { useWidgetConfig } from './hooks';

function WidgetSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr]">
      <div className="flex flex-col gap-4">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
      <Skeleton className="h-[480px] w-full" />
    </div>
  );
}

export function WidgetPage() {
  const { data: websites, isPending, isError, error, refetch } = useWebsites();
  const [selectedId, setSelectedId] = useState<string>('');

  const selected = selectedId || websites?.[0]?.id || null;
  const {
    data: widgetResponse,
    isPending: widgetPending,
    isError: widgetError,
    error: widgetErrorInfo,
    refetch: refetchWidget,
  } = useWidgetConfig(selected);

  if (isPending) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-4 w-72" />
        </div>
        <WidgetSkeleton />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Widget</h1>
          <p className="text-sm text-muted-foreground">
            Customize the chat widget for your websites.
          </p>
        </div>
        <EmptyState
          title="Could not load websites"
          description={error instanceof Error ? error.message : 'Something went wrong.'}
          actionLabel="Try again"
          onAction={() => void refetch()}
        />
      </div>
    );
  }

  const widgets = websites ?? [];

  if (widgets.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Widget</h1>
          <p className="text-sm text-muted-foreground">
            Customize the chat widget for your websites.
          </p>
        </div>
        <EmptyState
          icon={Puzzle}
          title="No websites yet"
          description="Create a website first, then customize its chat widget here."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-sans text-2xl font-bold tracking-tight">Widget</h1>
          <p className="text-sm text-muted-foreground">
            Customize the chat widget for your websites.
          </p>
        </div>
        <select
          aria-label="Select website"
          value={selected ?? ''}
          onChange={(event) => setSelectedId(event.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {widgets.map((site) => (
            <option key={site.id} value={site.id}>
              {site.name}
            </option>
          ))}
        </select>
      </div>

      {widgetPending ? (
        <WidgetSkeleton />
      ) : widgetError || !widgetResponse ? (
        <EmptyState
          title="Could not load widget"
          description={
            widgetErrorInfo instanceof Error ? widgetErrorInfo.message : 'Something went wrong.'
          }
          actionLabel="Try again"
          onAction={() => void refetchWidget()}
        />
      ) : (
        <WidgetEditor
          key={selected}
          config={widgetResponse.widget}
          embedScript={widgetResponse.embed_script}
        />
      )}
    </div>
  );
}
