'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { THEME_PRESETS, defaultTokens } from '@webchat/themes';

import { cn } from '@/lib/utils';
import type { WidgetThemePreset } from '../types';

/** Number of preset cards visible before "Show more" is revealed. */
const INITIAL_VISIBLE = 6;

const CLASSIC: WidgetThemePreset = '';

function ClassicCard({ selected }: { selected: boolean }) {
  // The "Classic" option maps to the fully-custom setup (`theme_preset = ''`),
  // which the theme engine resolves to `defaultTokens` (its actual palette) —
  // so the swatch mirrors what a no-preset widget really renders.
  const tokens = defaultTokens(false);
  return (
    <div className="overflow-hidden border-b border-border">
      <div
        className="h-12"
        style={{ background: `linear-gradient(135deg, ${tokens.primary}, ${tokens.accent})` }}
      />
      <div className="flex items-center gap-1.5 px-2 py-2" style={{ background: tokens.surface }}>
        <span className="size-3.5 rounded-full" style={{ background: tokens.primary }} />
        <span
          className="h-2.5 flex-1 rounded-full"
          style={{ background: tokens.assistantBubble }}
        />
        <span className="h-2.5 w-1/3 rounded-full" style={{ background: tokens.userBubble }} />
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

function PresetCard({
  preset,
  selected,
  onSelect,
}: {
  preset: (typeof THEME_PRESETS)[number];
  selected: boolean;
  onSelect: () => void;
}) {
  const tokens = preset.light;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={`Select ${preset.name} preset`}
      onClick={onSelect}
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
        <span className="h-2.5 w-1/3 rounded-full" style={{ background: tokens.userBubble }} />
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
}

export function ThemeSelector({
  value,
  onChange,
}: {
  value: WidgetThemePreset;
  onChange: (value: WidgetThemePreset) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const visiblePresets = expanded ? THEME_PRESETS : THEME_PRESETS.slice(0, INITIAL_VISIBLE);
  const hasMore = THEME_PRESETS.length > INITIAL_VISIBLE;

  return (
    <div className="flex flex-col gap-3">
      <div role="radiogroup" aria-label="Theme preset" className="grid grid-cols-2 gap-3">
        <button
          type="button"
          role="radio"
          aria-checked={value === CLASSIC}
          aria-label="Select Classic preset"
          onClick={() => onChange(CLASSIC)}
          className={cn(
            'overflow-hidden rounded-lg border bg-background text-left transition-colors',
            value === CLASSIC
              ? 'border-primary ring-2 ring-primary/20'
              : 'border-input hover:border-foreground/30',
          )}
        >
          <ClassicCard selected={value === CLASSIC} />
        </button>

        {visiblePresets.map((preset) => (
          <PresetCard
            key={preset.id}
            preset={preset}
            selected={value === preset.id}
            onSelect={() => onChange(preset.id)}
          />
        ))}
      </div>

      {hasMore ? (
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
          className="flex items-center justify-center gap-1.5 rounded-lg border border-input px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        >
          {expanded ? (
            <>
              <ChevronUp className="size-4" aria-hidden="true" />
              Show less
            </>
          ) : (
            <>
              <ChevronDown className="size-4" aria-hidden="true" />
              Show more ({THEME_PRESETS.length - INITIAL_VISIBLE} more)
            </>
          )}
        </button>
      ) : null}
    </div>
  );
}
