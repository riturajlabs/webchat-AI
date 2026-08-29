import type { Metadata } from 'next';

import { FaqSection } from '@/components/marketing/faq-section';
import { FeaturesSection } from '@/components/marketing/features-section';
import { FinalCta } from '@/components/marketing/final-cta';
import { Hero } from '@/components/marketing/hero';
import { HowItWorks } from '@/components/marketing/how-it-works';
import { Integrations } from '@/components/marketing/integrations';
import { Pricing } from '@/components/marketing/pricing';
import { ProductShowcase } from '@/components/marketing/product-showcase';
import { SocialProof } from '@/components/marketing/social-proof';
import { TrustSecurity } from '@/components/marketing/trust-security';
import { ValueProps } from '@/components/marketing/value-props';
import { SITE_DESCRIPTION } from '@/lib/site';
import { seoPage } from '@/lib/seo';

export const metadata: Metadata = seoPage({
  path: '/',
  title: 'WebChat AI - AI Chatbot for Your Website',
  absoluteTitle: true,
  description: SITE_DESCRIPTION,
});

export default function LandingPage() {
  return (
    <>
      <Hero />
      <SocialProof />
      <ProductShowcase />
      <ValueProps />
      <FeaturesSection />
      <HowItWorks />
      <Integrations />
      <TrustSecurity />
      <Pricing />
      <FaqSection />
      <FinalCta />
    </>
  );
}
