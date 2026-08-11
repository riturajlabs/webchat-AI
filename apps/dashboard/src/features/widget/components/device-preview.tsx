'use client';

import { Smartphone, Monitor } from 'lucide-react';

import { cn } from '@/lib/utils';

const DEVICES = [
  { id: 'desktop', label: 'Desktop', icon: Monitor },
  { id: 'mobile', label: 'Mobile', icon: Smartphone },
] as const;

export type DeviceId = (typeof DEVICES)[number]['id'];

export function DevicePreview({
  device,
  onDeviceChange,
  children,
  siteUrl,
}: {
  device: DeviceId;
  onDeviceChange: (device: DeviceId) => void;
  children: React.ReactNode;
  siteUrl?: string;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <div className="flex items-center gap-1 rounded-lg border bg-background p-1">
        {DEVICES.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            aria-pressed={device === id}
            onClick={() => onDeviceChange(id)}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
              device === id
                ? 'bg-accent font-medium text-accent-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Icon aria-hidden="true" className="size-4" />
            {label}
          </button>
        ))}
      </div>
      <div
        className={cn(
          'relative overflow-hidden rounded-xl border bg-white shadow-xl transition-all duration-200',
          device === 'mobile' ? 'w-[340px] sm:w-[380px]' : 'w-full max-w-2xl',
        )}
      >
        <div className="flex items-center gap-2 border-b bg-slate-100 px-3 py-2">
          <span className="flex gap-1">
            {['#ff5f57', '#febc2e', '#28c840'].map((color) => (
              <span
                key={color}
                className="size-2.5 rounded-full"
                style={{ backgroundColor: color }}
              />
            ))}
          </span>
          <span className="flex-1 truncate rounded-md bg-white/80 px-2 py-0.5 text-center text-xs text-slate-500">
            {siteUrl ?? 'https://your-site.com'}
          </span>
        </div>
        <div className="relative" style={{ height: device === 'mobile' ? 480 : 420 }}>
          {children}
        </div>
      </div>
    </div>
  );
}
