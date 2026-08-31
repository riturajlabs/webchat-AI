'use client';

import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Copy,
  FlaskConical,
  Globe,
  Loader2,
  MessagesSquare,
  Puzzle,
  Rocket,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { THEME_PRESETS } from '@webchat/themes';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { API_BASE_URL } from '@/lib/api';
import { useWebsites } from '@/features/websites/hooks';
import type { Website } from '@/features/websites/types';

import { AllowedDomainsEditor } from './components/allowed-domains-editor';
import { WidgetPreview } from './components/widget-preview';
import { useUpdateWidgetConfig, useWidgetConfig, useWidgetPublicStatus } from './hooks';
import type { WidgetConfig } from './types';
import { buildWidgetTestHtml, parseApiBaseUrl, parseScriptSrc } from './widget-test';

const STEPS = [
  { label: 'Customize', icon: Puzzle },
  { label: 'Domains', icon: Globe },
  { label: 'Install', icon: Rocket },
  { label: 'Test', icon: FlaskConical },
] as const;

function StepIndicator({ current, total }: { current: number; total: number }) {
  const percent = Math.round((current / total) * 100);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-muted-foreground">
          Step {current} of {total}
        </span>
        <span className="text-muted-foreground">{percent}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={`Setup progress: step ${current} of ${total}`}
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-blue-600 transition-all duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function StepNav({
  onBack,
  onNext,
  nextLabel,
  nextLoading,
  nextDisabled,
}: {
  onBack?: () => void;
  onNext: () => void;
  nextLabel?: string;
  nextLoading?: boolean;
  nextDisabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t pt-4">
      {onBack ? (
        <Button type="button" variant="ghost" onClick={onBack}>
          <ArrowLeft aria-hidden="true" />
          Back
        </Button>
      ) : (
        <div />
      )}
      <Button type="button" onClick={onNext} disabled={nextDisabled || nextLoading}>
        {nextLoading ? (
          <Loader2 className="animate-spin" aria-hidden="true" />
        ) : (
          <ArrowRight aria-hidden="true" />
        )}
        {nextLabel ?? 'Save & Continue'}
      </Button>
    </div>
  );
}

function CustomizeStep({
  config,
  onSave,
  onBack,
  onNext,
}: {
  config: WidgetConfig;
  onSave: (changes: Partial<WidgetConfig>) => Promise<void>;
  onBack?: () => void;
  onNext: () => void;
}) {
  const [draft, setDraft] = useState({
    bot_name: config.bot_name,
    theme: config.theme,
    theme_preset: config.theme_preset,
    welcome_message: config.welcome_message,
    primary_color: config.primary_color,
    accent_color: config.accent_color,
    position: config.position,
  });
  const [saving, setSaving] = useState(false);

  const previewConfig = useMemo(() => ({ ...config, ...draft }), [config, draft]);

  function patch(field: string, value: string) {
    setDraft((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(draft);
      toast.success('Widget appearance saved');
      onNext();
    } catch {
      toast.error('Failed to save widget settings');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3">
            <Label htmlFor="wizard-bot-name">Bot name</Label>
            <Input
              id="wizard-bot-name"
              value={draft.bot_name}
              onChange={(e) => patch('bot_name', e.target.value)}
              placeholder="Assistant"
            />
          </div>

          <div className="flex flex-col gap-3">
            <Label>Theme</Label>
            <div className="flex gap-2">
              {(['light', 'dark', 'auto'] as const).map((t) => (
                <Button
                  key={t}
                  type="button"
                  variant={draft.theme === t ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => patch('theme', t)}
                  className="capitalize"
                >
                  {t}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <Label>Theme preset</Label>
            <div className="flex flex-wrap gap-2">
              {[
                { value: '', label: 'None' },
                ...THEME_PRESETS.map((preset) => ({ value: preset.id, label: preset.name })),
              ].map((p) => (
                <Button
                  key={p.value}
                  type="button"
                  variant={draft.theme_preset === p.value ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => patch('theme_preset', p.value)}
                >
                  {p.label}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <Label htmlFor="wizard-welcome">Welcome message</Label>
            <Input
              id="wizard-welcome"
              value={draft.welcome_message}
              onChange={(e) => patch('welcome_message', e.target.value)}
              placeholder="Hi! How can I help you?"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor="wizard-primary-color">Primary color</Label>
              <div className="flex items-center gap-2">
                <input
                  id="wizard-primary-color"
                  type="color"
                  value={draft.primary_color}
                  onChange={(e) => patch('primary_color', e.target.value)}
                  className="size-8 cursor-pointer rounded border"
                />
                <Input
                  value={draft.primary_color}
                  onChange={(e) => patch('primary_color', e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="wizard-accent-color">Accent color</Label>
              <div className="flex items-center gap-2">
                <input
                  id="wizard-accent-color"
                  type="color"
                  value={draft.accent_color}
                  onChange={(e) => patch('accent_color', e.target.value)}
                  className="size-8 cursor-pointer rounded border"
                />
                <Input
                  value={draft.accent_color}
                  onChange={(e) => patch('accent_color', e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <Label>Position</Label>
            <div className="flex gap-2">
              {(['bottom-right', 'bottom-left'] as const).map((p) => (
                <Button
                  key={p}
                  type="button"
                  variant={draft.position === p ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => patch('position', p)}
                  className="capitalize"
                >
                  {p.replace('-', ' ')}
                </Button>
              ))}
            </div>
          </div>
        </div>

        <div className="sticky top-4 hidden lg:block">
          <WidgetPreview config={previewConfig} />
        </div>
      </div>

      <StepNav onBack={onBack} onNext={() => void handleSave()} nextLoading={saving} />
    </div>
  );
}

function DomainsStep({
  domains,
  onSave,
  onBack,
  onNext,
}: {
  domains: string[];
  onSave: (domains: string[]) => Promise<void>;
  onBack: () => void;
  onNext: () => void;
}) {
  const [draft, setDraft] = useState(domains);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(draft);
      toast.success('Domain allowlist saved');
      onNext();
    } catch {
      toast.error('Failed to save domains');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <AllowedDomainsEditor domains={draft} onChange={setDraft} />
      <StepNav onBack={onBack} onNext={() => void handleSave()} nextLoading={saving} />
    </div>
  );
}

function InstallStep({
  embedScript,
  onBack,
  onNext,
}: {
  embedScript: string;
  onBack: () => void;
  onNext: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copyEmbed() {
    try {
      await navigator.clipboard.writeText(embedScript);
      setCopied(true);
      toast.success('Embed code copied');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Failed to copy');
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        <div className="rounded-md border border-green-200 bg-green-50 p-4 dark:border-green-500/30 dark:bg-green-500/10">
          <p className="font-medium text-green-900 dark:text-green-400">Ready to install</p>
          <p className="mt-1 text-sm text-green-800 dark:text-green-300">
            Copy the script tag below and paste it into your website&apos;s HTML, just before the
            closing <code className="font-mono text-xs">&lt;/body&gt;</code> tag.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Label>Embed script</Label>
          <pre className="max-h-32 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
            {embedScript}
          </pre>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => void copyEmbed()}
          >
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            {copied ? 'Copied!' : 'Copy embed code'}
          </Button>
        </div>

        <div className="flex flex-col gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          <p className="font-medium text-foreground">Installation instructions</p>
          <ol className="list-inside list-decimal space-y-1">
            <li>Open your website&apos;s HTML file or CMS template editor.</li>
            <li>
              Paste the script tag just before the closing{' '}
              <code className="font-mono text-xs">&lt;/body&gt;</code> tag.
            </li>
            <li>Deploy your changes to production.</li>
            <li>
              Come back here and click <strong>Test</strong> to verify it works.
            </li>
          </ol>
        </div>
      </div>

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Continue to Test" />
    </div>
  );
}

function TestStep({
  widgetId,
  embedScript,
  onBack,
  onNext,
}: {
  widgetId: string;
  embedScript: string;
  onBack: () => void;
  onNext: () => void;
}) {
  const { data: status, isPending: statusPending } = useWidgetPublicStatus(widgetId);
  const scriptSrc = parseScriptSrc(embedScript);
  const apiBaseUrl = parseApiBaseUrl(embedScript) ?? API_BASE_URL;
  const previewHtml = scriptSrc ? buildWidgetTestHtml({ scriptSrc, widgetId, apiBaseUrl }) : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-2">
          <h3 className="font-sans text-base font-semibold">Live preview</h3>
          <p className="text-sm text-muted-foreground">
            The real widget SDK runs in this iframe using your current configuration.
          </p>
          {previewHtml ? (
            <iframe
              title="Widget live preview"
              className="h-[400px] w-full rounded-md border"
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
            <h3 className="font-sans text-base font-semibold">Connection check</h3>
            {statusPending ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                Checking origin guard…
              </p>
            ) : status ? (
              <div className="flex flex-col gap-2">
                {status.statusCode === 200 ? (
                  <p className="flex items-center gap-2 text-sm font-medium text-green-600">
                    <CheckCircle2 aria-hidden="true" className="size-4" />
                    200 OK — this origin is permitted
                  </p>
                ) : status.statusCode === 403 ? (
                  <div className="flex flex-col gap-2">
                    <p className="flex items-center gap-2 text-sm font-medium text-destructive">
                      <XCircle aria-hidden="true" className="size-4" />
                      403 Forbidden
                    </p>
                    <p className="rounded-md bg-destructive/10 px-3 py-2 font-mono text-xs">
                      {status.errorCode ?? 'UNKNOWN'}
                      {status.message ? ` — ${status.message}` : ''}
                    </p>
                  </div>
                ) : (
                  <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    {status.message ?? 'The widget API is unreachable from this origin.'}
                  </p>
                )}
                {status.allowedDomains && status.allowedDomains.length > 0 ? (
                  <div className="flex flex-col gap-1 text-sm">
                    <dt className="text-muted-foreground">Allowed domains:</dt>
                    <dd className="flex flex-wrap gap-1">
                      {status.allowedDomains.map((domain) => (
                        <code
                          key={domain}
                          className="rounded border px-1.5 py-0.5 font-mono text-xs"
                        >
                          {domain}
                        </code>
                      ))}
                    </dd>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No status available.</p>
            )}
          </section>

          <section className="flex flex-col gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            <p className="font-medium text-foreground">Testing on a real domain</p>
            <p>
              Add your production domain under <strong>Domains</strong> step, deploy the embed
              script to that domain, and verify the widget loads. The dashboard origin is always
              permitted for local testing.
            </p>
          </section>
        </div>
      </div>

      <StepNav onBack={onBack} onNext={onNext} nextLabel="Finish Setup" />
    </div>
  );
}

function CompletionStep() {
  return (
    <div className="flex flex-col items-center gap-6 py-8 text-center">
      <div className="flex size-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-500/20">
        <CheckCircle2 className="size-8 text-green-600 dark:text-green-400" aria-hidden="true" />
      </div>
      <div className="flex flex-col gap-2">
        <h2 className="text-2xl font-bold tracking-tight">Your AI assistant is live</h2>
        <p className="max-w-md text-muted-foreground">
          You&apos;ve completed the setup. Your chat widget is configured, domains are allowlisted,
          and the embed script is ready to deploy.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link href="/widget-test">
            <FlaskConical aria-hidden="true" />
            Open Widget Test
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/conversations">
            <MessagesSquare aria-hidden="true" />
            View Conversations
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/dashboard">
            <Puzzle aria-hidden="true" />
            Go to Dashboard
          </Link>
        </Button>
      </div>
    </div>
  );
}

export function WidgetSetupWizard() {
  const router = useRouter();
  const { data: websites, isPending, isError, error, refetch } = useWebsites();
  const [selectedId, setSelectedId] = useState('');
  const [step, setStep] = useState(0);
  const [completed, setCompleted] = useState(false);

  const selected = selectedId || websites?.[0]?.id || null;
  const {
    data: widgetResponse,
    isPending: widgetPending,
    isError: widgetError,
    error: widgetErrorInfo,
    refetch: refetchWidget,
  } = useWidgetConfig(selected);
  const updateConfig = useUpdateWidgetConfig();

  const websiteList: Website[] = websites ?? [];
  const config = widgetResponse?.widget ?? null;
  const embedScript = widgetResponse?.embed_script ?? '';

  const handleSaveConfig = useCallback(
    async (changes: Partial<WidgetConfig>) => {
      if (!selected || !config) return;
      await updateConfig.mutateAsync({ websiteId: selected, changes });
      await refetchWidget();
    },
    [selected, config, updateConfig, refetchWidget],
  );

  const handleSaveDomains = useCallback(
    async (domains: string[]) => {
      if (!selected || !config) return;
      await updateConfig.mutateAsync({
        websiteId: selected,
        changes: { allowed_domains: domains },
      });
      await refetchWidget();
    },
    [selected, config, updateConfig, refetchWidget],
  );

  if (isPending) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-72" />
        </div>
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col gap-6">
        <EmptyState
          title="Could not load websites"
          description={error instanceof Error ? error.message : 'Something went wrong.'}
          actionLabel="Try again"
          onAction={() => void refetch()}
        />
      </div>
    );
  }

  if (websiteList.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <EmptyState
          icon={Puzzle}
          title="No websites yet"
          description="Add a website first, then come back to set up its chat widget."
          actionLabel="Add a website"
          onAction={() => router.push('/websites')}
        />
      </div>
    );
  }

  if (completed) {
    return (
      <div className="flex flex-col gap-6">
        <CompletionStep />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-sans text-2xl font-bold tracking-tight">Widget Setup Assistant</h1>
        <p className="text-sm text-muted-foreground">
          Set up your chat widget in a few simple steps.
        </p>
      </div>

      {websiteList.length > 1 ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor="wizard-website">Website</Label>
          <select
            id="wizard-website"
            aria-label="Select website"
            value={selected ?? ''}
            onChange={(e) => setSelectedId(e.target.value)}
            className="h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:w-auto"
          >
            {websiteList.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          Setting up widget for <strong>{websiteList[0]?.name}</strong>
        </p>
      )}

      <StepIndicator current={step + 1} total={STEPS.length} />

      <nav aria-label="Setup steps" className="flex gap-1 overflow-x-auto">
        {STEPS.map(({ label, icon: Icon }, i) => (
          <button
            key={label}
            type="button"
            onClick={() => i <= step && setStep(i)}
            disabled={i > step}
            className={cn(
              'flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-colors',
              i === step
                ? 'bg-primary text-primary-foreground'
                : i < step
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground',
              i > step && 'cursor-not-allowed opacity-50',
            )}
            aria-current={i === step ? 'step' : undefined}
          >
            {i < step ? (
              <Check className="size-4" aria-hidden="true" />
            ) : (
              <Icon className="size-4" aria-hidden="true" />
            )}
            {label}
          </button>
        ))}
      </nav>

      {widgetPending ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : widgetError || !config ? (
        <EmptyState
          title="Could not load widget"
          description={
            widgetErrorInfo instanceof Error ? widgetErrorInfo.message : 'Something went wrong.'
          }
          actionLabel="Try again"
          onAction={() => void refetchWidget()}
        />
      ) : (
        <>
          {step === 0 && (
            <CustomizeStep
              config={config}
              onSave={handleSaveConfig}
              onBack={undefined}
              onNext={() => setStep(1)}
            />
          )}
          {step === 1 && (
            <DomainsStep
              domains={config.allowed_domains ?? []}
              onSave={handleSaveDomains}
              onBack={() => setStep(0)}
              onNext={() => setStep(2)}
            />
          )}
          {step === 2 && (
            <InstallStep
              embedScript={embedScript}
              onBack={() => setStep(1)}
              onNext={() => setStep(3)}
            />
          )}
          {step === 3 && (
            <TestStep
              widgetId={config.widget_id}
              embedScript={embedScript}
              onBack={() => setStep(2)}
              onNext={() => setCompleted(true)}
            />
          )}
        </>
      )}
    </div>
  );
}
