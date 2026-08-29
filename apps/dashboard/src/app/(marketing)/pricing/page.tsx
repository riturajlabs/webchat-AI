import { FaqSection } from '@/components/marketing/faq-section';
import { FinalCta } from '@/components/marketing/final-cta';
import { MarketingPageHeader } from '@/components/marketing/marketing-page-header';
import { Pricing } from '@/components/marketing/pricing';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/pricing',
  title: 'Pricing',
  description:
    'Free to start, transparent upgrades. Pick a plan that matches how much your assistant works for you.',
});

export default function PricingPage() {
  return (
    <>
      <MarketingPageHeader
        title="Pricing"
        description="Free to start, transparent upgrades. Pick a plan that matches how much your assistant works for you."
      />
      <Pricing />
      <FaqSection />
      <FinalCta />
    </>
  );
}
