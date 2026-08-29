'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';

import { FAQ_ITEMS } from './faq-data';
import { SectionHeading } from './section-heading';

export function FaqSection() {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="faq" className="scroll-mt-20 border-t border-border/60 bg-muted/30">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading eyebrow="FAQ" title="Frequently asked questions" />
        <div className="mx-auto mt-12 flex max-w-2xl flex-col gap-3">
          {FAQ_ITEMS.map(({ question, answer }, index) => {
            const open = openIndex === index;
            return (
              <div key={question} className="rounded-lg border border-border/60 bg-card shadow-sm">
                <h3>
                  <button
                    type="button"
                    id={`faq-button-${index}`}
                    aria-expanded={open}
                    aria-controls={`faq-panel-${index}`}
                    onClick={() => setOpenIndex(open ? null : index)}
                    className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left text-sm font-medium transition-colors hover:text-blue-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring dark:hover:text-blue-400"
                  >
                    {question}
                    <ChevronDown
                      className={`size-4 shrink-0 text-muted-foreground transition-transform duration-200 ${
                        open ? 'rotate-180' : ''
                      }`}
                      aria-hidden="true"
                    />
                  </button>
                </h3>
                <div
                  id={`faq-panel-${index}`}
                  role="region"
                  aria-labelledby={`faq-button-${index}`}
                  className={`grid transition-all duration-200 ease-out ${
                    open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
                  }`}
                >
                  <div className="overflow-hidden">
                    <p className="px-4 pb-4 text-sm leading-relaxed text-muted-foreground">
                      {answer}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
