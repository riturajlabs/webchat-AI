import { FinalCta } from '@/components/marketing/final-cta';
import { HowItWorks } from '@/components/marketing/how-it-works';
import { MarketingPageHeader } from '@/components/marketing/marketing-page-header';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/how-it-works',
  title: 'How it works',
  description:
    'Three steps from your website to a live AI assistant: connect your site, build the knowledge base and embed the widget.',
});

export default function HowItWorksPage() {
  return (
    <>
      <MarketingPageHeader
        title="How it works"
        description="Three steps from your website to a live AI assistant: connect your site, build the knowledge base and embed the widget."
      />
      <HowItWorks />
      <FinalCta />
    </>
  );
}
