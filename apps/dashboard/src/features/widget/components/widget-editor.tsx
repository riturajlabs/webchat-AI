'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, Loader2, Save } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

import { AllowedDomainsEditor } from './allowed-domains-editor';
import { ColorPicker } from './color-picker';
import { EmbedCode } from './embed-code';
import { QuestionEditor } from './question-editor';
import { ThemeSelector } from './theme-selector';
import { WidgetPreview } from './widget-preview';
import { useUpdateWidgetConfig } from '../hooks';
import type { WidgetConfig, WidgetConfigChanges } from '../types';

const EDITABLE_FIELDS: (keyof WidgetConfigChanges)[] = [
  'theme',
  'theme_preset',
  'position',
  'primary_color',
  'accent_color',
  'font_size',
  'logo_url',
  'avatar_url',
  'welcome_message',
  'placeholder',
  'suggested_questions',
  'branding',
  'dark_mode',
  'auto_open',
  'enabled',
  'allowed_domains',
  'bot_name',
  'bot_status_text',
  'header_color',
  'secondary_color',
  'background_color',
  'text_color',
  'font_family',
  'width',
  'height',
  'border_radius',
  'launcher_size',
];

const UNSAVED_MESSAGE = 'You have unsaved widget changes. Leave anyway?';

function GroupHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
      {children}
    </h2>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex flex-col gap-0.5">
        <Label>{label}</Label>
        <span className="text-sm text-muted-foreground">{description}</span>
      </div>
      <button
        type="button"
        role="switch"
        aria-label={label}
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          checked ? 'bg-blue-600' : 'bg-input',
        )}
      >
        <span
          className={cn(
            'absolute left-0.5 top-0.5 size-5 rounded-full bg-white shadow transition-transform',
            checked && 'translate-x-5',
          )}
        />
      </button>
    </div>
  );
}

function OptionalColorPicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        <button
          type="button"
          onClick={() => onChange(null)}
          disabled={value === null}
          className="rounded text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
        >
          Reset to default
        </button>
      </div>
      <ColorPicker label={label} value={value ?? '#000000'} onChange={onChange} />
    </div>
  );
}

export function WidgetEditor({
  config,
  embedScript,
  onDirtyChange,
}: {
  config: WidgetConfig;
  embedScript: string;
  onDirtyChange?: (isDirty: boolean) => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<WidgetConfig>(config);
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const updateWidget = useUpdateWidgetConfig();

  const changes = useMemo(() => {
    const diff: Partial<WidgetConfigChanges> = {};
    for (const field of EDITABLE_FIELDS) {
      const next = draft[field];
      const current = config[field];
      if (Array.isArray(next)) {
        if (JSON.stringify(next) !== JSON.stringify(current)) {
          (diff as Record<string, unknown>)[field] = next;
        }
      } else if (next !== current) {
        (diff as Record<string, unknown>)[field] = next;
      }
    }
    return diff;
  }, [draft, config]);

  const isDirty = Object.keys(changes).length > 0;

  useEffect(() => {
    onDirtyChange?.(isDirty);
    return () => onDirtyChange?.(false);
  }, [isDirty, onDirtyChange]);

  useEffect(() => {
    if (!isDirty) {
      return;
    }
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isDirty]);

  useEffect(() => {
    if (!isDirty) {
      return;
    }
    function handleClick(event: MouseEvent) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const anchor = (event.target as Element | null)?.closest('a[href]');
      if (!anchor) {
        return;
      }
      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('#')) {
        return;
      }
      if (!window.confirm(UNSAVED_MESSAGE)) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      router.push(href);
    }
    document.addEventListener('click', handleClick, true);
    return () => document.removeEventListener('click', handleClick, true);
  }, [isDirty, router]);

  function patch(partial: Partial<WidgetConfigChanges>) {
    setDraft((current) => ({ ...current, ...partial }));
  }

  async function save() {
    try {
      const result = await updateWidget.mutateAsync({ websiteId: config.website_id, changes });
      setDraft(result.widget);
      setLastSavedAt(Date.now());
      toast.success('Widget settings saved');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save widget settings.');
    }
  }

  const saveStatus = updateWidget.isPending
    ? 'saving'
    : isDirty
      ? 'unsaved'
      : lastSavedAt !== null
        ? 'saved'
        : 'idle';

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr] xl:grid-cols-[minmax(0,460px)_1fr]">
      <div className="flex min-w-0 flex-col gap-5">
        <div className="sticky top-0 z-10 -mx-1 flex flex-wrap items-center justify-between gap-3 rounded-b-lg border-b bg-background/95 px-1 pb-3 pt-1 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="min-w-0">
            <h2 className="font-sans text-lg font-semibold">Customize widget</h2>
            <p className="text-sm text-muted-foreground">
              Changes appear in the preview instantly.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span aria-live="polite" className="text-sm">
              {saveStatus === 'saving' ? (
                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  Saving…
                </span>
              ) : saveStatus === 'unsaved' ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
                  <span className="size-1.5 rounded-full bg-amber-500" aria-hidden="true" />
                  Unsaved changes
                </span>
              ) : saveStatus === 'saved' ? (
                <span className="inline-flex items-center gap-1.5 text-green-700 dark:text-green-400">
                  <Check className="size-4" aria-hidden="true" />
                  Saved
                </span>
              ) : null}
            </span>
            <Button onClick={save} disabled={!isDirty || updateWidget.isPending}>
              {updateWidget.isPending ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  Saving…
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <Save aria-hidden="true" />
                  Save changes
                </span>
              )}
            </Button>
          </div>
        </div>

        <section aria-labelledby="appearance-heading" className="flex flex-col gap-3">
          <GroupHeading>
            <span id="appearance-heading">Appearance</span>
          </GroupHeading>
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-base">Theme &amp; colors</CardTitle>
              <CardDescription className="text-sm">
                Pick a curated palette or fine-tune every color yourself.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 p-4 pt-2">
              <ThemeSelector
                value={draft.theme_preset}
                onChange={(theme_preset) => patch({ theme_preset })}
              />
              {draft.theme_preset ? (
                <p className="text-xs text-muted-foreground">
                  Custom colors set below override this preset.
                </p>
              ) : null}
              <Field id="theme" label="Theme">
                <select
                  id="theme"
                  value={draft.theme}
                  onChange={(event) =>
                    patch({ theme: event.target.value as WidgetConfig['theme'] })
                  }
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                  <option value="auto">Auto</option>
                </select>
              </Field>
              <ColorPicker
                label="Primary color"
                value={draft.primary_color}
                onChange={(primary_color) => patch({ primary_color })}
              />
              <ColorPicker
                label="Accent color"
                value={draft.accent_color}
                onChange={(accent_color) => patch({ accent_color })}
              />
              <OptionalColorPicker
                label="Header color"
                value={draft.header_color}
                onChange={(header_color) => patch({ header_color })}
              />
              <OptionalColorPicker
                label="Secondary color"
                value={draft.secondary_color}
                onChange={(secondary_color) => patch({ secondary_color })}
              />
              <OptionalColorPicker
                label="Background color"
                value={draft.background_color}
                onChange={(background_color) => patch({ background_color })}
              />
              <OptionalColorPicker
                label="Text color"
                value={draft.text_color}
                onChange={(text_color) => patch({ text_color })}
              />
              <Field id="font-family" label="Font family">
                <Input
                  id="font-family"
                  value={draft.font_family ?? ''}
                  maxLength={100}
                  placeholder="System default"
                  onChange={(event) => patch({ font_family: event.target.value || null })}
                />
              </Field>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-base">Brand &amp; identity</CardTitle>
              <CardDescription className="text-sm">
                Bot name, avatar and logos shown to visitors.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 p-4 pt-2">
              <Field id="bot-name" label="Bot name">
                <Input
                  id="bot-name"
                  value={draft.bot_name}
                  maxLength={60}
                  placeholder="WebChat AI"
                  onChange={(event) => patch({ bot_name: event.target.value })}
                />
              </Field>
              <Field id="bot-status" label="Status text">
                <Input
                  id="bot-status"
                  value={draft.bot_status_text}
                  maxLength={40}
                  placeholder="Online"
                  onChange={(event) => patch({ bot_status_text: event.target.value })}
                />
              </Field>
              <Field id="logo-url" label="Logo URL">
                <Input
                  id="logo-url"
                  value={draft.logo_url ?? ''}
                  placeholder="https://…"
                  onChange={(event) => patch({ logo_url: event.target.value || null })}
                />
              </Field>
              <Field id="avatar-url" label="Avatar URL">
                <Input
                  id="avatar-url"
                  value={draft.avatar_url ?? ''}
                  placeholder="https://…"
                  onChange={(event) => patch({ avatar_url: event.target.value || null })}
                />
              </Field>
              <Toggle
                label="Show branding"
                description="Display the WebChat AI badge on the widget."
                checked={draft.branding}
                onChange={(branding) => patch({ branding })}
              />
            </CardContent>
          </Card>
        </section>

        <section aria-labelledby="behavior-heading" className="flex flex-col gap-3">
          <GroupHeading>
            <span id="behavior-heading">Chat behavior</span>
          </GroupHeading>
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-base">Messages</CardTitle>
              <CardDescription className="text-sm">
                Greeting, placeholder and suggested questions for new visitors.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 p-4 pt-2">
              <Field id="welcome-message" label="Welcome message">
                <Input
                  id="welcome-message"
                  value={draft.welcome_message}
                  maxLength={500}
                  onChange={(event) => patch({ welcome_message: event.target.value })}
                />
              </Field>
              <Field id="placeholder" label="Input placeholder">
                <Input
                  id="placeholder"
                  value={draft.placeholder}
                  maxLength={120}
                  onChange={(event) => patch({ placeholder: event.target.value })}
                />
              </Field>
              <QuestionEditor
                questions={draft.suggested_questions}
                onChange={(suggested_questions) => patch({ suggested_questions })}
              />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-base">Engagement</CardTitle>
              <CardDescription className="text-sm">
                How and when the widget engages visitors.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 p-4 pt-2">
              <Toggle
                label="Auto open"
                description="Open the chat window automatically for new visitors."
                checked={draft.auto_open}
                onChange={(auto_open) => patch({ auto_open })}
              />
              <Toggle
                label="Enabled"
                description="Disable to hide the widget from your site entirely."
                checked={draft.enabled}
                onChange={(enabled) => patch({ enabled })}
              />
            </CardContent>
          </Card>
        </section>

        <section aria-labelledby="position-heading" className="flex flex-col gap-3">
          <GroupHeading>
            <span id="position-heading">Position &amp; size</span>
          </GroupHeading>
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-base">Placement</CardTitle>
              <CardDescription className="text-sm">
                Where the widget sits and how large it renders.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 p-4 pt-2">
              <Field id="position" label="Position">
                <select
                  id="position"
                  value={draft.position}
                  onChange={(event) =>
                    patch({ position: event.target.value as WidgetConfig['position'] })
                  }
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="bottom-right">Bottom Right</option>
                  <option value="bottom-left">Bottom Left</option>
                </select>
              </Field>
              <Field id="font-size" label="Font size">
                <select
                  id="font-size"
                  value={draft.font_size}
                  onChange={(event) =>
                    patch({ font_size: event.target.value as WidgetConfig['font_size'] })
                  }
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="sm">Small</option>
                  <option value="md">Medium</option>
                  <option value="lg">Large</option>
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field id="width" label="Width">
                  <Input
                    id="width"
                    value={draft.width}
                    maxLength={20}
                    placeholder="420px"
                    onChange={(event) => patch({ width: event.target.value })}
                  />
                </Field>
                <Field id="height" label="Height">
                  <Input
                    id="height"
                    value={draft.height}
                    maxLength={20}
                    placeholder="650px"
                    onChange={(event) => patch({ height: event.target.value })}
                  />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field id="border-radius" label="Corner radius">
                  <Input
                    id="border-radius"
                    value={draft.border_radius}
                    maxLength={20}
                    placeholder="20px"
                    onChange={(event) => patch({ border_radius: event.target.value })}
                  />
                </Field>
                <Field id="launcher-size" label="Launcher size">
                  <Input
                    id="launcher-size"
                    value={draft.launcher_size}
                    maxLength={20}
                    placeholder="58px"
                    onChange={(event) => patch({ launcher_size: event.target.value })}
                  />
                </Field>
              </div>
            </CardContent>
          </Card>
        </section>

        <Card>
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-base">Allowed domains</CardTitle>
            <CardDescription className="text-sm">
              Restrict which websites may embed this widget.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-4 pt-2">
            <AllowedDomainsEditor
              domains={draft.allowed_domains}
              onChange={(allowed_domains) => patch({ allowed_domains })}
            />
          </CardContent>
        </Card>

        <EmbedCode widgetId={config.widget_id} embedScript={embedScript} />
      </div>

      <div className="flex flex-col gap-3 lg:sticky lg:top-6 lg:self-start">
        <div>
          <h2 className="font-sans text-lg font-semibold">Live preview</h2>
          <p className="text-sm text-muted-foreground">
            See your changes exactly as visitors will.
          </p>
        </div>
        <div className="overflow-x-auto pb-2">
          <WidgetPreview config={draft} />
        </div>
      </div>
    </div>
  );
}
