import { SectionHeading } from './section-heading';

const STEPS = [
  {
    title: 'Connect your website',
    description: 'Add your website URL in the dashboard — WebChat AI starts crawling your pages.',
  },
  {
    title: 'Train the knowledge base',
    description:
      'Crawled content is chunked and embedded, building a knowledge base unique to your site.',
  },
  {
    title: 'Embed the chatbot',
    description:
      'Paste one script tag into your site. Your assistant appears as a chat widget, styled to match your brand.',
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
        <SectionHeading
          eyebrow="How it works"
          title="Live in three steps"
          description="No infrastructure to run and no training data to collect — start from what you already have."
        />
        <ol className="mt-12 grid gap-8 sm:grid-cols-3 sm:gap-4">
          {STEPS.map(({ title, description }, index) => (
            <li key={title} className="flex flex-col items-center gap-4 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-600 text-lg font-bold text-white shadow-sm">
                {index + 1}
              </span>
              <div className="max-w-xs">
                <h3 className="text-base font-semibold">{title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{description}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
