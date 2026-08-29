import { FinalCta } from '@/components/marketing/final-cta';
import { MarketingPageHeader } from '@/components/marketing/marketing-page-header';
import { TrustSecurity } from '@/components/marketing/trust-security';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/security',
  title: 'Security',
  description:
    "How WebChat AI keeps your data and your visitors' conversations safe — secure widget, domain control and privacy by default.",
});

export default function SecurityPage() {
  return (
    <>
      <MarketingPageHeader
        title="Security"
        description="How WebChat AI keeps your data and your visitors' conversations safe — secure widget, domain control and privacy by default."
      />
      <TrustSecurity />
      <FinalCta />
    </>
  );
}
