'use client';

import { Bot, Check, Quote, Send, Sparkles } from 'lucide-react';

const SUGGESTED_QUESTIONS = [
  'How do I install it?',
  'What integrations are supported?',
  'Is pricing per website?',
];

export function WidgetShowcase() {
  return (
    <div aria-hidden="true" className="relative mx-auto w-full max-w-md">
      <div
        className="absolute -left-8 -top-8 h-40 w-40 rounded-full bg-blue-500/10 blur-3xl"
        aria-hidden="true"
      />
      <div
        className="absolute -bottom-8 -right-8 h-40 w-40 rounded-full bg-amber-400/15 blur-3xl"
        aria-hidden="true"
      />
      <div className="relative overflow-hidden rounded-2xl border border-border/60 bg-card shadow-xl">
        <div className="flex items-center gap-3 px-4 py-3 bg-brand-gradient">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20">
            <Bot className="size-5 text-white" />
          </span>
          <div className="flex-1">
            <p className="text-sm font-semibold text-white">Website Assistant</p>
            <span className="inline-flex items-center gap-1 text-[11px] text-white/80">
              <span className="size-1.5 rounded-full bg-green-300" />
              Grounded in your content
            </span>
          </div>
          <Sparkles className="size-4 text-white/80" aria-hidden="true" />
        </div>

        <div className="flex flex-col gap-3.5 px-4 py-5">
          <div className="max-w-[85%] self-start rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2.5 text-sm">
            Hi! Ask me anything about this website — pricing, setup, integrations and more.
          </div>
          <div className="max-w-[85%] self-end rounded-2xl rounded-br-sm bg-blue-600 px-3.5 py-2.5 text-sm text-white">
            How do I get started?
          </div>
          <div className="self-start">
            <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2.5 text-sm">
              <p>
                Connect your site in the dashboard, let WebChat AI crawl and index it, then paste
                one script tag to go live.
              </p>
              <span className="mt-2 inline-flex items-center gap-1 rounded-md bg-blue-600/10 px-2 py-1 text-[11px] font-medium text-blue-700 dark:text-blue-400">
                <Quote className="size-3" aria-hidden="true" />
                Source: docs/getting-started
              </span>
            </div>
          </div>

          {/* Streaming indicator */}
          <div className="self-start">
            <div className="rounded-2xl rounded-bl-sm bg-muted px-4 py-3 text-sm">
              <span className="flex items-center gap-1.5">
                <span
                  className="size-1.5 animate-pulse rounded-full bg-blue-600"
                  style={{ animationDelay: '0ms' }}
                />
                <span
                  className="size-1.5 animate-pulse rounded-full bg-blue-600"
                  style={{ animationDelay: '150ms' }}
                />
                <span
                  className="size-1.5 animate-pulse rounded-full bg-blue-600"
                  style={{ animationDelay: '300ms' }}
                />
                <span className="ml-1 text-xs text-muted-foreground">Writing answer…</span>
              </span>
            </div>
          </div>

          <div className="mt-1 flex flex-wrap gap-2">
            {SUGGESTED_QUESTIONS.map((question) => (
              <span
                key={question}
                className="rounded-full border border-border bg-background px-3 py-1.5 text-xs text-muted-foreground"
              >
                {question}
              </span>
            ))}
          </div>

          <div className="mt-2 flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2">
            <span className="flex-1 text-sm text-muted-foreground">Type your message…</span>
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600">
              <Send className="size-3 text-white" aria-hidden="true" />
            </span>
          </div>
        </div>
      </div>

      {/* Floating demo cards (clearly illustrative) */}
      <span className="absolute -right-6 top-16 hidden flex-col gap-1 rounded-lg border border-border/60 bg-card px-3 py-2 shadow-md sm:flex">
        <span className="text-[11px] text-muted-foreground">Knowledge base</span>
        <span className="flex items-center gap-1 text-xs font-semibold">
          <Check className="size-3 text-green-600" aria-hidden="true" />
          156 pages indexed
        </span>
      </span>
      <span className="absolute -left-6 bottom-16 hidden flex-col gap-1 rounded-lg border border-border/60 bg-card px-3 py-2 shadow-md sm:flex">
        <span className="text-[11px] text-muted-foreground">AI answers</span>
        <span className="flex items-center gap-1 text-xs font-semibold">
          <Sparkles className="size-3 text-blue-600" aria-hidden="true" />
          Grounded in your content
        </span>
      </span>
    </div>
  );
}
