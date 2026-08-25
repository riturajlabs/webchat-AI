import { SITE_DESCRIPTION, SITE_NAME, SITE_URL } from '@/lib/site';

const FAQ_DATA = [
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

function OrganizationJsonLd() {
  const data = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: SITE_NAME,
    url: SITE_URL,
    logo: `${SITE_URL}/opengraph-image`,
    description: SITE_DESCRIPTION,
    sameAs: [],
  };

  return (
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />
  );
}

function SoftwareApplicationJsonLd() {
  const data = {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: SITE_NAME,
    url: SITE_URL,
    applicationCategory: 'BusinessApplication',
    operatingSystem: 'Web',
    description: SITE_DESCRIPTION,
    offers: {
      '@type': 'Offer',
      price: '0',
      priceCurrency: 'USD',
      description: 'Free plan available',
    },
    featureList: [
      'AI Chatbot',
      'RAG Knowledge Base',
      'Website Crawling',
      'Conversation Analytics',
      'Custom Widget Themes',
      'REST API',
    ],
  };

  return (
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />
  );
}

function FaqJsonLd() {
  const data = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: FAQ_DATA.map(({ question, answer }) => ({
      '@type': 'Question',
      name: question,
      acceptedAnswer: {
        '@type': 'Answer',
        text: answer,
      },
    })),
  };

  return (
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />
  );
}

export function MarketingStructuredData() {
  return (
    <>
      <OrganizationJsonLd />
      <SoftwareApplicationJsonLd />
      <FaqJsonLd />
    </>
  );
}
