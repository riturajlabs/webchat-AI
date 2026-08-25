import { ChevronDown } from 'lucide-react';

import { SectionHeading } from './section-heading';

const FAQS = [
  {
    question: 'How does the assistant answer questions?',
    answer:
      'WebChat AI crawls your website and stores the content as documents in a vector knowledge base. Visitor questions retrieve the most relevant passages, so answers are grounded in your own pages.',
  },
  {
    question: 'Do I need to write code to install it?',
    answer:
      'No. Copy the embed script from Widget → Embed code in your dashboard and paste it into your site. For framework apps, an SDK package with init() and mount() helpers is also documented.',
  },
  {
    question: 'Can I control where the widget appears?',
    answer:
      'Yes. A new widget is seeded with your registered hostname only, so it can be embedded just there. You can add bare hostnames or wildcards like *.example.com — and an empty allowlist blocks embedding entirely.',
  },
  {
    question: 'Can I customize how the widget looks and behaves?',
    answer:
      'The widget builder covers theme presets and brand colors, welcome message, suggested questions, launcher position, font size, dark mode and auto-open — with changes reflected instantly in a live preview.',
  },
  {
    question: 'Is my data secure?',
    answer:
      'The widget carries no secrets: it authenticates with short-lived, server-issued session tokens. The backend checks the embedding origin on every request, applies rate limits, screens spam and uses a non-PII cookie identifier for visitors.',
  },
  {
    question: 'The widget does not appear on my page — what now?',
    answer:
      'Confirm your website is ready and the widget is enabled in the dashboard, then hard refresh — config is cached for up to five minutes. A 403 error means the embedding origin is not in your allowed domains list.',
  },
];

export function FaqSection() {
  return (
    <section id="faq" className="scroll-mt-20 border-t border-border/60 bg-muted/30">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading eyebrow="FAQ" title="Frequently asked questions" />
        <div className="mx-auto mt-12 flex max-w-2xl flex-col gap-3">
          {FAQS.map(({ question, answer }) => (
            <details
              key={question}
              className="group rounded-lg border border-border/60 bg-card shadow-sm"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3.5 text-sm font-medium [&::-webkit-details-marker]:hidden">
                {question}
                <ChevronDown
                  className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                  aria-hidden="true"
                />
              </summary>
              <p className="px-4 pb-4 text-sm text-muted-foreground">{answer}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
