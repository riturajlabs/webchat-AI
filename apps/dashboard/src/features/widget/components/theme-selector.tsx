'use client';

import { THEME_PRESETS } from '@webchat/themes';

import { cn } from '@/lib/utils';
import type { WidgetThemePreset } from '../types';

function ClassicCard({ selected }: { selected: boolean }) {
  return (
    <div className="overflow-hidden border-b border-border">
      <div
        className="h-12"
        style={{
          background: `linear-gradient(135deg, #2563eb, #f59e0b)`,
        }}
      />
      <div className="flex items-center gap-1.5 px-2 py-2">
        <span className="size-3.5 rounded-full bg-slate-200" />
        <span className="h-2.5 flex-1 rounded-full bg-slate-200" />
        <span className="h-2.5 w-1/3 rounded-full bg-blue-500" />
      </div>
      <div className="px-2 pb-2">
        <p className="text-sm font-medium">Classic</p>
        <p className="text-xs text-muted-foreground">Your custom colors</p>
      </div>
      {selected ? (
        <div className="flex items-center justify-between px-2 pb-2">
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
            Active
          </span>
        </div>
      ) : null}
    </div>
  );
}

export function ThemeSelector({
  value,
  onChange,
}: {
  value: WidgetThemePreset;
  onChange: (value: WidgetThemePreset) => void;
}) {
  return (
    <div role="radiogroup" aria-label="Theme preset" className="grid grid-cols-2 gap-3">
      <button
        type="button"
        role="radio"
        aria-checked={value === ''}
        aria-label="Select Classic preset"
        onClick={() => onChange('')}
        className={cn(
          'overflow-hidden rounded-lg border bg-background text-left transition-colors',
          value === ''
            ? 'border-primary ring-2 ring-primary/20'
            : 'border-input hover:border-foreground/30',
        )}
      >
        <ClassicCard selected={value === ''} />
      </button>

      {THEME_PRESETS.map((preset) => {
        const tokens = preset.light;
        const selected = value === preset.id;
        return (
          <button
            key={preset.id}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={`Select ${preset.name} preset`}
            onClick={() => onChange(preset.id as WidgetThemePreset)}
            className={cn(
              'overflow-hidden rounded-lg border bg-background text-left transition-colors',
              selected
                ? 'border-primary ring-2 ring-primary/20'
                : 'border-input hover:border-foreground/30',
            )}
          >
            <div
              className="h-12"
              style={{
                background: preset.headerGradient
                  ? `linear-gradient(135deg, ${tokens.primary}, ${tokens.accent})`
                  : tokens.header,
              }}
            />
            <div
              className="flex items-center gap-1.5 border-b border-border px-2 py-2"
              style={{ background: tokens.surface }}
            >
              <span className="size-3.5 rounded-full" style={{ background: tokens.primary }} />
              <span
                className="h-2.5 flex-1 rounded-full"
                style={{ background: tokens.assistantBubble }}
              />
              <span
                className="h-2.5 w-1/3 rounded-full"
                style={{ background: tokens.userBubble }}
              />
            </div>
            <div className="px-2 py-2">
              <p className="text-sm font-medium">{preset.name}</p>
              <p className="text-xs text-muted-foreground">{preset.description}</p>
            </div>
            {selected ? (
              <div className="flex items-center justify-between px-2 pb-2">
                <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                  Active
                </span>
              </div>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
