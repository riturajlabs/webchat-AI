'use client';

/* eslint-disable @next/next/no-img-element -- live SDK-style preview uses raw <img> (arbitrary user URLs) */

import { useState } from 'react';
import { Send, X } from 'lucide-react';
import { resolveTheme } from '@webchat/themes';

import { DeviceId, DevicePreview } from './device-preview';
import type { WidgetConfig } from '../types';

const FONT_SIZES: Record<string, string> = {
  sm: '14px',
  md: '16px',
  lg: '18px',
};

function effectiveDark(config: WidgetConfig): boolean {
  if (config.theme === 'dark') return true;
  if (config.theme === 'auto' && typeof window !== 'undefined') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  if (config.dark_mode) return true;
  return false;
}

function parseCssLength(value: string, fallback: number): number {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  // vw/vh/em/rem aren't meaningful inside the phone preview; px is the norm.
  return Math.min(parsed, 520);
}

/**
 * Live widget preview (Phase 11.5).
 *
 * A faithful React re-creation of the `@webchat/widget` SDK look - same CSS
 * tokens (`--wc-*` → inline styles, same radius/shadow/font-size mapping) so
 * the builder shows exactly what the live embed will look like. Colors are
 * resolved by the shared `@webchat/themes` engine (`resolveTheme`), the same
 * one the widget runtime applies, so preset and custom themes render
 * identically here and on the live embed. It only renders the config; no SDK
 * runtime behavior is mounted.
 */
export function WidgetPreview({ config }: { config: WidgetConfig }) {
  const [device, setDevice] = useState<DeviceId>('desktop');
  const [open, setOpen] = useState(true);

  const dark = effectiveDark(config);
  const fontPx = FONT_SIZES[config.font_size] ?? FONT_SIZES.md;
  const left = config.position === 'bottom-left';

  const theme = resolveTheme(config, dark);
  const radius = parseCssLength(config.border_radius, 12);
  const width = parseCssLength(config.width, 360);
  const launcherSize = parseCssLength(config.launcher_size, 56);
  const botName = config.bot_name.trim() || (config.branding ? 'WebChat AI' : 'Assistant');
  const statusText = config.bot_status_text.trim() || 'Online';

  const scrollbarStyle = {
    scrollbarWidth: 'thin' as const,
    scrollbarColor: `${theme.scrollbarThumb} ${theme.scrollbarTrack}`,
  };

  return (
    <DevicePreview siteUrl="https://your-site.com" device={device} onDeviceChange={setDevice}>
      <div
        className="relative h-full w-full overflow-hidden"
        style={{ background: dark ? '#020617' : '#f8fafc', fontFamily: 'Inter, sans-serif' }}
      >
        <img
          src={`https://placehold.co/1200x800?text=${encodeURIComponent('Your website')}`}
          alt=""
          aria-hidden="true"
          className="h-full w-full object-cover opacity-40"
        />

        {open ? (
          <div
            className="absolute flex flex-col overflow-hidden"
            style={{
              [left ? 'left' : 'right']: 20,
              bottom: 88,
              width,
              height: 'calc(100% - 108px)',
              maxHeight: 460,
              borderRadius: radius,
              background: theme.surface,
              border: `1px solid ${theme.border}`,
              boxShadow: '0 16px 48px rgba(2, 6, 23, 0.22)',
              fontSize: fontPx,
              color: theme.text,
              fontFamily: config.font_family ?? 'Inter, sans-serif',
            }}
            role="dialog"
            aria-label="Assistant preview"
          >
            <div
              className="flex items-center gap-2 px-4 py-3"
              style={{
                background: theme.header,
                color: theme.headerText,
                borderTopLeftRadius: radius,
                borderTopRightRadius: radius,
              }}
            >
              <div className="flex size-8 items-center justify-center overflow-hidden rounded-full bg-white/20">
                {config.avatar_url ? (
                  <img src={config.avatar_url} alt="" className="size-full object-cover" />
                ) : (
                  <span className="text-sm font-semibold">AI</span>
                )}
              </div>
              <div className="flex flex-col">
                <span className="text-sm font-semibold leading-tight">{botName}</span>
                <span className="text-xs opacity-90">{statusText}</span>
              </div>
              <button
                type="button"
                aria-label="Close preview"
                onClick={() => setOpen(false)}
                className="ml-auto rounded-full p-1 hover:bg-white/20"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </div>

            <div className="flex-1 overflow-hidden px-4 pb-2 pt-1" style={scrollbarStyle}>
              {config.welcome_message ? (
                <p
                  className="py-2 text-center text-[0.85em]"
                  style={{ color: theme.muted, fontStyle: 'italic' }}
                >
                  {config.welcome_message}
                </p>
              ) : null}
              <div
                className="mb-2 flex max-w-[80%] items-center gap-2 rounded-xl px-3 py-2"
                style={{
                  background: theme.assistantBubble,
                  color: theme.text,
                  fontSize: '0.9em',
                }}
              >
                <div
                  className="flex size-5 shrink-0 items-center justify-center rounded-full bg-white/40 text-[10px] font-semibold"
                  style={{ color: theme.muted }}
                >
                  AI
                </div>
                <span>Hi! I’m your AI assistant. Ask me anything about this site.</span>
              </div>
              <div
                className="mb-2 ml-auto w-fit max-w-[80%] rounded-xl px-3 py-2"
                style={{
                  background: theme.userBubble,
                  color: theme.userText,
                  fontSize: '0.9em',
                }}
              >
                What do you offer?
              </div>
            </div>

            {config.suggested_questions.length > 0 ? (
              <div className="flex flex-wrap gap-2 px-4 pb-2 pt-1">
                <span className="w-full text-xs" style={{ color: theme.muted }}>
                  Try asking:
                </span>
                {config.suggested_questions.slice(0, 3).map((question) => (
                  <span
                    key={question}
                    className="rounded-full border px-3 py-1 text-xs"
                    style={{
                      borderColor: theme.border,
                      color: theme.text,
                      background: theme.surface,
                    }}
                  >
                    {question}
                  </span>
                ))}
              </div>
            ) : null}

            <div
              className="flex items-end gap-2 border-t px-3 py-2"
              style={{ borderColor: theme.border }}
            >
              <div
                className="flex-1 rounded-full border px-3 py-2 text-[0.85em]"
                style={{
                  background: theme.inputBg,
                  borderColor: theme.border,
                  color: theme.muted,
                }}
              >
                {config.placeholder || 'Type your message…'}
              </div>
              <button
                type="button"
                aria-label="Send"
                className="flex size-9 items-center justify-center rounded-full text-white"
                style={{
                  background: `linear-gradient(135deg, ${theme.primary}, ${theme.secondary})`,
                }}
              >
                <Send aria-hidden="true" className="size-4" />
              </button>
            </div>

            {config.branding ? (
              <p
                className="border-t py-1.5 text-center text-[0.7em]"
                style={{ color: theme.muted, borderColor: 'transparent' }}
              >
                Powered by WebChat AI
              </p>
            ) : null}
          </div>
        ) : null}

        <button
          type="button"
          aria-label="Open assistant"
          onClick={() => setOpen((value) => !value)}
          className="absolute flex items-center justify-center rounded-full text-white shadow-lg transition-transform hover:scale-105"
          style={{
            [left ? 'left' : 'right']: 20,
            bottom: 20,
            width: launcherSize,
            height: launcherSize,
            background: `linear-gradient(135deg, ${theme.primary}, ${theme.secondary})`,
          }}
        >
          {open ? (
            <X aria-hidden="true" className="size-6" />
          ) : (
            <img
              src="data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/%3E%3C/svg%3E"
              alt=""
              aria-hidden="true"
              className="size-6"
            />
          )}
        </button>
      </div>
    </DevicePreview>
  );
}
