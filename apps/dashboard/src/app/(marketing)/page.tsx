import { Faq } from './sections/faq';
import { Features } from './sections/features';
import { FinalCta } from './sections/final-cta';
import { Hero } from './sections/hero';
import { HowItWorks } from './sections/how-it-works';
import { PricingTeaser } from './sections/pricing-teaser';

export default function LandingPage() {
  return (
    <>
      <Hero />
      <Features />
      <HowItWorks />
      <PricingTeaser />
      <Faq />
      <FinalCta />
    </>
  );
}
