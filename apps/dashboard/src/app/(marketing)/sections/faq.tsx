import { ChevronDown } from 'lucide-react';

const FAQS = [
  {
    question: 'How does the assistant learn my website?',
    answer:
      'You add your website URL in the dashboard. The crawler fetches your public pages, splits them into chunks, and builds a searchable index. Retrieval-augmented generation uses that index to compose answers, so responses reflect your actual content.',
  },
  {
    question: 'Where do the answers come from?',
    answer:
      'Only from the knowledge base built for that website. Answers cite the sources they used, and the widget renders those citations as clickable chips so visitors can verify claims.',
  },
  {
    question: 'Can I customize how the widget looks?',
    answer:
      'Yes. Pick a theme preset or set custom primary and accent colors, upload a logo and avatar, choose the launcher corner, edit the welcome message and suggested questions, and toggle the "Powered by" badge.',
  },
  {
    question: 'Is it safe to embed on my domain?',
    answer:
      'The widget only runs on domains you explicitly allow-list per website. All remote assets are restricted to https URLs, and the docs include a CSP snippet (connect-src) for stricter sites.',
  },
  {
    question: 'What happens when the assistant does not know an answer?',
    answer:
      'It says so instead of guessing — generation is grounded in retrieved content with confidence handling. Every conversation is recorded in the dashboard, so you can spot gaps and improve your content.',
  },
  {
    question: 'Do I need to write code to use it?',
    answer:
      'No. Embedding is a single script tag copied from the dashboard. Everything else — websites, knowledge base, themes, analytics — is managed through the web dashboard.',
  },
];

export function Faq() {
  return (
    <section id="faq" className="scroll-mt-14 border-b bg-muted/30">
      <div className="mx-auto w-full max-w-3xl px-4 py-16 md:px-6 md:py-24">
        <div className="mb-10 flex flex-col gap-3">
          <h2 className="font-sans text-3xl font-bold tracking-tight">
            Frequently asked questions
          </h2>
          <p className="text-muted-foreground">
            Everything about how WebChat AI learns from your site and serves your visitors.
          </p>
        </div>
        <div className="flex flex-col gap-3">
          {FAQS.map(({ question, answer }) => (
            <details
              key={question}
              className="group rounded-lg border bg-background p-4 [&_summary::-webkit-details-marker]:hidden"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                {question}
                <ChevronDown
                  className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                  aria-hidden="true"
                />
              </summary>
              <p className="mt-3 text-sm text-muted-foreground">{answer}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
