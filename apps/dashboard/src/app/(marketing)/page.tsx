import type { Metadata } from 'next';

import { FaqSection } from '@/components/marketing/faq-section';
import { FeaturesSection } from '@/components/marketing/features-section';
import { FinalCta } from '@/components/marketing/final-cta';
import { Hero } from '@/components/marketing/hero';
import { HowItWorks } from '@/components/marketing/how-it-works';
import { PricingTeaser } from '@/components/marketing/pricing-teaser';
import { TrustSecurity } from '@/components/marketing/trust-security';

export const metadata: Metadata = {
  title: {
    absolute: 'WebChat AI - AI Chatbot for Your Website',
  },
  description: 'Build intelligent AI assistants trained on your website content.',
};

export default function LandingPage() {
  return (
    <>
      <Hero />
      <FeaturesSection />
      <HowItWorks />
      <TrustSecurity />
      <PricingTeaser />
      <FaqSection />
      <FinalCta />
    </>
  );
}
