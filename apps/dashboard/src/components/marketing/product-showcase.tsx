import {
  BarChart3,
  Bot,
  CheckCircle2,
  Globe,
  MessageSquare,
  Send,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react';

import { SectionHeading } from './section-heading';

const STAT_CARDS = [
  { icon: MessageSquare, label: 'Conversations', value: '2,847', trend: '+12%' },
  { icon: CheckCircle2, label: 'Resolved', value: '94.2%', trend: '+3.1%' },
  { icon: Globe, label: 'Pages indexed', value: '156', trend: '+8' },
];

const BAR_HEIGHTS = [30, 55, 40, 72, 50, 85, 65, 45, 78, 60, 42, 70];

const CHAT_MESSAGES = [
  { role: 'user', text: 'How do I integrate the widget with React?' },
  {
    role: 'assistant',
    text: (
      <>
        Import the SDK, call <code className="font-mono text-[11px]">init()</code> and{' '}
        <code className="font-mono text-[11px]">mount()</code> — see the Embed docs for the full
        example.
      </>
    ),
  },
  { role: 'user', text: 'Can I customize the theme?' },
  {
    role: 'assistant',
    text: 'Yes. Choose from 7 theme presets or set brand colors, welcome messages and position from the widget builder.',
  },
];

export function ProductShowcase() {
  return (
    <section id="product" className="scroll-mt-20 border-t border-border/60">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="Product"
          title="Your AI assistant, fully managed"
          description="From crawling your content to serving conversations — everything runs in one dashboard."
        />
        <div className="relative mt-12">
          <div
            className="absolute -inset-4 -z-10 rounded-3xl bg-brand-gradient-subtle opacity-30 blur-2xl"
            aria-hidden="true"
          />
          <div className="grid gap-6 lg:grid-cols-5">
            {/* Dashboard panel */}
            <div className="overflow-hidden rounded-2xl border border-border/60 bg-card shadow-xl lg:col-span-3">
              {/* Browser chrome */}
              <div className="flex items-center gap-2 border-b border-border/60 bg-muted/50 px-4 py-2.5">
                <span className="flex gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-red-400/80" />
                  <span className="h-3 w-3 rounded-full bg-amber-400/80" />
                  <span className="h-3 w-3 rounded-full bg-green-400/80" />
                </span>
                <div className="ml-3 flex flex-1 items-center rounded-md bg-background/80 px-3 py-1 text-xs text-muted-foreground">
                  dashboard.webchatai.com/websites
                </div>
              </div>
              <div className="p-5">
                {/* Assistant header */}
                <div className="mb-5 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white">
                      <Bot className="size-5" />
                    </span>
                    <div>
                      <p className="text-sm font-semibold">My Website Assistant</p>
                      <div className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                        <span className="text-xs text-muted-foreground">Active</span>
                      </div>
                    </div>
                  </div>
                  <span className="flex items-center gap-1 rounded-md bg-green-500/10 px-2 py-1 text-xs font-medium text-green-700 dark:text-green-400">
                    <Zap className="size-3" aria-hidden="true" />
                    Live
                  </span>
                </div>
                {/* Stat cards */}
                <div className="mb-4 grid grid-cols-3 gap-3">
                  {STAT_CARDS.map(({ icon: Icon, label, value, trend }) => (
                    <div
                      key={label}
                      className="rounded-lg border border-border/60 bg-background p-3"
                    >
                      <div className="mb-1.5 flex items-center gap-1.5">
                        <Icon className="size-3.5 text-muted-foreground" />
                        <span className="text-[11px] text-muted-foreground">{label}</span>
                      </div>
                      <p className="text-lg font-bold leading-none">{value}</p>
                      <span className="mt-1 inline-flex items-center gap-0.5 text-[11px] font-medium text-green-600 dark:text-green-400">
                        <TrendingUp className="size-2.5" aria-hidden="true" />
                        {trend}
                      </span>
                    </div>
                  ))}
                </div>
                {/* Mini chart */}
                <div className="rounded-lg border border-border/60 bg-background p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium">Conversations this week</span>
                    <BarChart3 className="size-3.5 text-muted-foreground" />
                  </div>
                  <div className="flex items-end gap-[3px]" style={{ height: 52 }}>
                    {BAR_HEIGHTS.map((h, i) => (
                      <div
                        key={i}
                        className="flex-1 rounded-t bg-blue-600/70 dark:bg-blue-500/70"
                        style={{ height: `${h}%` }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Widget panel */}
            <div className="flex flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-xl lg:col-span-2">
              {/* Widget header */}
              <div className="flex items-center gap-3 bg-brand-gradient px-4 py-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20">
                  <Sparkles className="size-4 text-white" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-white">Website Assistant</p>
                  <p className="text-[11px] text-white/80">Powered by your content</p>
                </div>
              </div>
              {/* Chat messages */}
              <div className="flex flex-1 flex-col gap-3 px-4 py-4">
                {CHAT_MESSAGES.map(({ role, text }, i) => (
                  <div
                    key={i}
                    className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm ${
                      role === 'user'
                        ? 'self-end rounded-br-sm bg-blue-600 text-white'
                        : 'self-start rounded-bl-sm bg-muted'
                    }`}
                  >
                    {text}
                  </div>
                ))}
              </div>
              {/* Input bar */}
              <div className="border-t border-border/60 px-4 py-3">
                <div className="flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2.5">
                  <span className="flex-1 text-sm text-muted-foreground">Ask a follow-up...</span>
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600">
                    <Send className="size-3 text-white" />
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
