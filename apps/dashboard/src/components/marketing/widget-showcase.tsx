import { Bot } from 'lucide-react';

const SUGGESTED_QUESTIONS = ['What do you offer?', 'How do I install it?'];

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
          <div>
            <p className="text-sm font-semibold text-white">Website Assistant</p>
            <p className="text-xs text-white/80">Powered by your content</p>
          </div>
        </div>
        <div className="flex flex-col gap-3 px-4 py-5">
          <div className="max-w-[85%] self-start rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2.5 text-sm">
            Hi! Ask me anything about this website.
          </div>
          <div className="max-w-[85%] self-end rounded-2xl rounded-br-sm bg-blue-600 px-3.5 py-2.5 text-sm text-white">
            Where can I find your documentation?
          </div>
          <div className="max-w-[85%] self-start rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2.5 text-sm">
            Everything lives under Docs — installation, configuration and troubleshooting guides
            included.
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
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                className="size-3.5 text-white"
              >
                <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
          </div>
        </div>
      </div>
      <span className="absolute -bottom-5 -right-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 shadow-lg ring-4 ring-background">
        <Bot className="size-6 text-white" />
      </span>
    </div>
  );
}
