'use client';

import { useMemo, useState } from 'react';
import { Save } from 'lucide-react';
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
import { WidgetPreview } from './widget-preview';
import { useUpdateWidgetConfig } from '../hooks';
import type { WidgetConfig, WidgetConfigChanges } from '../types';

const EDITABLE_FIELDS: (keyof WidgetConfigChanges)[] = [
  'theme',
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
];

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription className="text-sm">{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 p-4 pt-2">{children}</CardContent>
    </Card>
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
          'relative h-6 w-11 shrink-0 rounded-full transition-colors',
          checked ? 'bg-primary' : 'bg-input',
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

export function WidgetEditor({
  config,
  embedScript,
}: {
  config: WidgetConfig;
  embedScript: string;
}) {
  const [draft, setDraft] = useState<WidgetConfig>(config);
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

  function patch(partial: Partial<WidgetConfigChanges>) {
    setDraft((current) => ({ ...current, ...partial }));
  }

  async function save() {
    try {
      const result = await updateWidget.mutateAsync({ websiteId: config.website_id, changes });
      setDraft(result.widget);
      toast.success('Widget settings saved');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save widget settings.');
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr] xl:grid-cols-[minmax(0,460px)_1fr]">
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-sans text-lg font-semibold">Customize widget</h2>
            <p className="text-sm text-muted-foreground">
              Changes appear in the preview instantly.
            </p>
          </div>
          <Button onClick={save} disabled={!isDirty || updateWidget.isPending}>
            {updateWidget.isPending ? (
              <span className="flex items-center gap-2">
                <span className="size-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
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

        <Section
          title="Appearance"
          description="Colors, fonts and how the widget looks on your site."
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="theme">Theme</Label>
            <select
              id="theme"
              value={draft.theme}
              onChange={(event) => patch({ theme: event.target.value as WidgetConfig['theme'] })}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
              <option value="auto">Auto</option>
            </select>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="position">Position</Label>
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
          </div>

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

          <div className="flex flex-col gap-2">
            <Label htmlFor="font-size">Font size</Label>
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
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="logo-url">Logo URL</Label>
            <Input
              id="logo-url"
              value={draft.logo_url ?? ''}
              placeholder="https://…"
              onChange={(event) => patch({ logo_url: event.target.value || null })}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="avatar-url">Avatar URL</Label>
            <Input
              id="avatar-url"
              value={draft.avatar_url ?? ''}
              placeholder="https://…"
              onChange={(event) => patch({ avatar_url: event.target.value || null })}
            />
          </div>

          <Toggle
            label="Show branding"
            description="Display the WebChat AI badge on the widget."
            checked={draft.branding}
            onChange={(branding) => patch({ branding })}
          />
        </Section>

        <Section title="Messages" description="Greeting and suggested questions for new visitors.">
          <div className="flex flex-col gap-2">
            <Label htmlFor="welcome-message">Welcome message</Label>
            <Input
              id="welcome-message"
              value={draft.welcome_message}
              maxLength={500}
              onChange={(event) => patch({ welcome_message: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="placeholder">Input placeholder</Label>
            <Input
              id="placeholder"
              value={draft.placeholder}
              maxLength={120}
              onChange={(event) => patch({ placeholder: event.target.value })}
            />
          </div>
          <QuestionEditor
            questions={draft.suggested_questions}
            onChange={(suggested_questions) => patch({ suggested_questions })}
          />
        </Section>

        <Section title="Behavior" description="How and when the widget engages visitors.">
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
        </Section>

        <Section
          title="Allowed domains"
          description="Restrict which websites may embed this widget."
        >
          <AllowedDomainsEditor
            domains={draft.allowed_domains}
            onChange={(allowed_domains) => patch({ allowed_domains })}
          />
        </Section>

        <EmbedCode widgetId={config.widget_id} embedScript={embedScript} />
      </div>

      <div className="flex items-start justify-center lg:sticky lg:top-6">
        <WidgetPreview config={draft} />
      </div>
    </div>
  );
}
