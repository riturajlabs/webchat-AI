import { FeaturesSection } from '@/components/marketing/features-section';
import { FinalCta } from '@/components/marketing/final-cta';
import { MarketingPageHeader } from '@/components/marketing/marketing-page-header';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/features',
  title: 'Features',
  description:
    'Everything you need to put a grounded AI assistant on your website — crawling, RAG knowledge base, analytics and more.',
});

export default function FeaturesPage() {
  return (
    <>
      <MarketingPageHeader
        title="Features"
        description="Everything you need to put a grounded AI assistant on your website — crawling, RAG knowledge base, analytics and more."
      />
      <FeaturesSection />
      <FinalCta />
    </>
  );
}
