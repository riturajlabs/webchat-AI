'use client';

import { useId, useState } from 'react';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

const PRESETS = [
  '#2563eb',
  '#4f46e5',
  '#0f766e',
  '#059669',
  '#d97706',
  '#dc2626',
  '#db2777',
  '#000000',
];

export function ColorPicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  const [text, setText] = useState(value);

  function commit(next: string) {
    const normalized = next.trim();
    if (HEX_COLOR.test(normalized)) {
      onChange(normalized.toLowerCase());
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="color"
          value={HEX_COLOR.test(value) ? value : '#000000'}
          onChange={(event) => {
            setText(event.target.value);
            onChange(event.target.value);
          }}
          className="size-9 shrink-0 cursor-pointer rounded-md border border-input bg-background p-1"
          aria-label={`${label} color swatch`}
        />
        <Input
          value={text}
          maxLength={7}
          aria-label={`${label} hex value`}
          onChange={(event) => {
            const next = event.target.value;
            setText(next);
            if (HEX_COLOR.test(next.trim())) {
              commit(next);
            }
          }}
          onBlur={() => setText(value)}
          className="font-mono"
        />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((color) => (
          <button
            key={color}
            type="button"
            aria-label={`Set ${label.toLowerCase()} to ${color}`}
            onClick={() => {
              setText(color);
              onChange(color);
            }}
            className={`size-6 rounded-full border transition-transform hover:scale-110 ${
              value.toLowerCase() === color ? 'ring-2 ring-ring ring-offset-2' : 'border-border'
            }`}
            style={{ backgroundColor: color }}
          />
        ))}
      </div>
    </div>
  );
}
