import { Code2, Globe, LibraryBig } from 'lucide-react';

const STEPS = [
  {
    icon: Globe,
    step: 'Step 1',
    title: 'Add your website',
    description:
      'Point WebChat AI at your site URL. The crawler fetches your public pages and builds a dedicated knowledge base.',
  },
  {
    icon: LibraryBig,
    step: 'Step 2',
    title: 'AI learns your content',
    description:
      'Pages are chunked, embedded, and indexed for hybrid retrieval, so every answer is grounded in what your site actually says.',
  },
  {
    icon: Code2,
    step: 'Step 3',
    title: 'Embed the widget',
    description:
      'Paste one script tag into your site. Configure themes, questions, and behavior from the dashboard — updates go live instantly.',
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-14 border-b bg-muted/30">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 md:px-6 md:py-24">
        <div className="mb-10 flex max-w-2xl flex-col gap-3">
          <h2 className="font-sans text-3xl font-bold tracking-tight">How it works</h2>
          <p className="text-muted-foreground">
            From live URL to embedded assistant in three steps.
          </p>
        </div>
        <ol className="grid gap-4 md:grid-cols-3">
          {STEPS.map(({ icon: Icon, step, title, description }) => (
            <li key={step} className="flex flex-col gap-3 rounded-lg border bg-background p-5">
              <span className="flex h-9 w-9 items-center justify-center rounded-md border">
                <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
              </span>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {step}
              </p>
              <h3 className="font-medium">{title}</h3>
              <p className="text-sm text-muted-foreground">{description}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
