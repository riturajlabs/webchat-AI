'use client';

import { useState } from 'react';
import { CheckCircle2, FlaskConical, Globe, Link2, XCircle } from 'lucide-react';

import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { API_BASE_URL } from '@/lib/api';
import { useWebsites } from '@/features/websites/hooks';

import { useWidgetConfig, useWidgetPublicStatus } from './hooks';
import { buildWidgetTestHtml, parseApiBaseUrl, parseScriptSrc } from './widget-test';

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="break-all font-mono text-sm">{value}</dd>
    </div>
  );
}

function TestSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Skeleton className="h-[480px] w-full" />
      <div className="flex flex-col gap-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  );
}

export function WidgetTestPage() {
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

  const widgetId = widgetResponse?.widget.widget_id ?? null;
  const { data: status, isPending: statusPending } = useWidgetPublicStatus(widgetId);

  if (isPending) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-4 w-72" />
        </div>
        <TestSkeleton />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col gap-6">
        <Header />
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
        <Header />
        <EmptyState
          icon={FlaskConical}
          title="No websites yet"
          description="Create a website first, then test its widget here."
        />
      </div>
    );
  }

  const scriptSrc = widgetResponse ? parseScriptSrc(widgetResponse.embed_script) : null;
  const apiBaseUrl = widgetResponse
    ? (parseApiBaseUrl(widgetResponse.embed_script) ?? API_BASE_URL)
    : null;
  const previewHtml =
    scriptSrc && widgetId
      ? buildWidgetTestHtml({ scriptSrc, widgetId, apiBaseUrl: apiBaseUrl ?? undefined })
      : null;
  const browserOrigin = typeof window !== 'undefined' ? window.location.origin : '';

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Header />
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
        <TestSkeleton />
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
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="flex flex-col gap-2">
            <h2 className="font-sans text-base font-semibold">Live preview</h2>
            <p className="text-sm text-muted-foreground">
              The real widget SDK runs in this iframe. It inherits the dashboard origin, so the
              backend always permits it — use this page to sanity-check the widget, then verify a
              customer domain by embedding on that domain.
            </p>
            {previewHtml ? (
              <iframe
                title="Widget live preview"
                className="h-[480px] w-full rounded-md border"
                sandbox="allow-scripts allow-same-origin"
                srcDoc={previewHtml}
              />
            ) : (
              <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                The embed script has no script src to load.
              </p>
            )}
          </div>

          <div className="flex flex-col gap-4">
            <section className="flex flex-col gap-3 rounded-md border p-4">
              <h2 className="font-sans text-base font-semibold">Connection details</h2>
              <dl className="flex flex-col gap-3">
                <InfoRow label="Widget ID" value={widgetResponse.widget.widget_id} />
                <InfoRow label="Embed script src" value={scriptSrc ?? '—'} />
                <InfoRow label="Widget API URL" value={`${API_BASE_URL}/api/widget/v1`} />
                <InfoRow
                  label="Browser origin (sent as Origin header)"
                  value={browserOrigin || '—'}
                />
              </dl>
            </section>

            <section className="flex flex-col gap-3 rounded-md border p-4">
              <h2 className="flex items-center gap-2 font-sans text-base font-semibold">
                <Globe aria-hidden="true" className="size-4 text-muted-foreground" />
                Origin guard check
              </h2>
              {statusPending ? (
                <p className="text-sm text-muted-foreground">Checking the origin guard…</p>
              ) : status ? (
                <StatusReport status={status} />
              ) : (
                <p className="text-sm text-muted-foreground">No status available.</p>
              )}
            </section>

            <section className="flex flex-col gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              <p className="flex items-center gap-2 font-medium text-foreground">
                <Link2 aria-hidden="true" className="size-4" />
                Testing a real customer domain
              </p>
              <p>
                The dashboard origin is always permitted (configured dashboard origins). To verify a
                production embed, add your site&apos;s domain under{' '}
                <span className="font-mono text-xs">Widget → Allowed domains</span> and load the
                embed script on that domain — the browser will send that origin, and the guard will
                answer 200 or 403.
              </p>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function Header() {
  return (
    <PageHeader
      title="Widget Test"
      description="Preview the real widget and check the origin guard from your browser."
    />
  );
}

function StatusReport({
  status,
}: {
  status: {
    statusCode: number;
    enabled?: boolean;
    allowedDomains?: string[];
    errorCode?: string;
    message?: string;
  };
}) {
  if (status.statusCode === 200) {
    return (
      <div className="flex flex-col gap-2">
        <p className="flex items-center gap-2 text-sm font-medium text-green-600">
          <CheckCircle2 aria-hidden="true" className="size-4" />
          200 OK — this origin is permitted
        </p>
        <dl className="flex flex-col gap-2 text-sm">
          <div className="flex items-center gap-2">
            <dt className="text-muted-foreground">Widget enabled:</dt>
            <dd>{status.enabled ? 'yes' : 'no'}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-muted-foreground">Allowed domains:</dt>
            <dd className="flex flex-wrap gap-1">
              {status.allowedDomains && status.allowedDomains.length > 0 ? (
                status.allowedDomains.map((domain) => (
                  <code key={domain} className="rounded border px-1.5 py-0.5 font-mono text-xs">
                    {domain}
                  </code>
                ))
              ) : (
                <span className="text-muted-foreground">
                  none (embeds blocked until configured)
                </span>
              )}
            </dd>
          </div>
        </dl>
      </div>
    );
  }

  if (status.statusCode === 403) {
    return (
      <div className="flex flex-col gap-2">
        <p className="flex items-center gap-2 text-sm font-medium text-destructive">
          <XCircle aria-hidden="true" className="size-4" />
          403 Forbidden — the origin guard rejected this request
        </p>
        <p className="rounded-md bg-destructive/10 px-3 py-2 font-mono text-xs">
          {status.errorCode ?? 'UNKNOWN'}
          {status.message ? ` — ${status.message}` : ''}
        </p>
        <p className="text-sm text-muted-foreground">
          {status.errorCode === 'WIDGET_DOMAIN_NOT_CONFIGURED'
            ? 'The widget has no allowed domains yet. Add your domain under Widget → Allowed domains.'
            : 'This origin is not in the widget allowlist. Add it under Widget → Allowed domains, or check that the API runs in development mode.'}
        </p>
      </div>
    );
  }

  if (status.statusCode === 0) {
    return (
      <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
        {status.message ?? 'The widget API is unreachable from this origin.'}
      </p>
    );
  }

  return (
    <p className="rounded-md bg-destructive/10 px-3 py-2 font-mono text-xs">
      HTTP {status.statusCode}
      {status.errorCode ? ` ${status.errorCode}` : ''}
      {status.message ? ` — ${status.message}` : ''}
    </p>
  );
}
