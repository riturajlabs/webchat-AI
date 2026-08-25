import { BarChart3, Bot, LibraryBig, Puzzle } from 'lucide-react';

const FEATURES = [
  {
    icon: Bot,
    title: 'AI website chatbot',
    description:
      'An embeddable chat widget that greets visitors, offers suggested questions, and follows your light/dark/auto theme with configurable positioning.',
  },
  {
    icon: LibraryBig,
    title: 'RAG knowledge retrieval',
    description:
      'Answers are generated from your indexed site content using hybrid retrieval and reranking — and cite the sources they came from.',
  },
  {
    icon: BarChart3,
    title: 'Analytics',
    description:
      'See how visitors use your assistant: conversation volume, question trends, and usage metering across every website you connect.',
  },
  {
    icon: Puzzle,
    title: 'Custom widget',
    description:
      'Theme presets, custom colors, logo, avatar, welcome message, suggested questions — secured to your own domains via an allowlist.',
  },
];

export function Features() {
  return (
    <section id="features" className="scroll-mt-14 border-b">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 md:px-6 md:py-24">
        <div className="mb-10 flex max-w-2xl flex-col gap-3">
          <h2 className="font-sans text-3xl font-bold tracking-tight">Everything you need</h2>
          <p className="text-muted-foreground">
            A complete pipeline from your live website content to a production-ready chat assistant.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, description }) => (
            <article
              key={title}
              className="flex flex-col gap-3 rounded-lg border bg-background p-5"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-md border">
                <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
              </span>
              <h3 className="font-medium">{title}</h3>
              <p className="text-sm text-muted-foreground">{description}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
