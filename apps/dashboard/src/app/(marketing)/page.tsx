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

export const metadata: Metadata = {
  title: {
    absolute: 'WebChat AI - AI Chatbot for Your Website',
  },
  description:
    'Build an AI chatbot trained on your website content. Answer visitor questions automatically, 24/7 — live in minutes, zero code.',
};

export default function LandingPage() {
  return (
    <>
      <Hero />
      <SocialProof />
      <ProductShowcase />
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
