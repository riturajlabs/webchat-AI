/**
 * Single source of truth for the marketing FAQ content.
 *
 * Shared by the interactive `FaqSection` and the `FAQPage` JSON-LD structured
 * data so search-engine structured data never drifts from visible content.
 */
export interface FaqItem {
  question: string;
  answer: string;
}

export const FAQ_ITEMS: FaqItem[] = [
  {
    question: 'How does WebChat AI answer questions?',
    answer:
      'WebChat AI crawls your website and stores the content as documents in a vector knowledge base. Visitor questions retrieve the most relevant passages, so answers are grounded in your own pages.',
  },
  {
    question: 'Do I need to write code to install it?',
    answer:
      'No. Copy the embed script from Widget → Embed code in your dashboard and paste it into your site. For framework apps, an SDK package with init() and mount() helpers is also documented.',
  },
  {
    question: 'How long does setup take?',
    answer:
      'Once you add a website, crawling and indexing start automatically. Most sites are ready to serve answers within a few minutes, and you paste one script tag to go live.',
  },
  {
    question: 'Where does the assistant get its answers?',
    answer:
      'Solely from the pages you have indexed. WebChat AI retrieves the most relevant passages from your knowledge base for each question and cites the source it used.',
  },
  {
    question: 'Can I control which domains use the widget?',
    answer:
      'Yes. A new widget is seeded with your registered hostname only, so it can be embedded just there. You can add bare hostnames or wildcards like *.example.com — and an empty allowlist blocks embedding entirely.',
  },
  {
    question: 'Can I customize how the widget looks and behaves?',
    answer:
      'The widget builder covers theme presets and brand colors, welcome message, suggested questions, launcher position, font size, dark mode and auto-open — with changes reflected instantly in a live preview.',
  },
  {
    question: 'Can I integrate it with my existing website?',
    answer:
      'Yes. A single script tag works on any HTML site, and an SDK is provided for React and Next.js apps. A REST API with API keys covers programmatic integrations.',
  },
  {
    question: 'Is my data secure?',
    answer:
      'The widget carries no secrets: it authenticates with short-lived, server-issued session tokens. The backend checks the embedding origin on every request, applies rate limits, screens spam and uses a non-PII cookie identifier for visitors.',
  },
];
