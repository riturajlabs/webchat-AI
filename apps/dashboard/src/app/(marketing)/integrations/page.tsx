import { FinalCta } from '@/components/marketing/final-cta';
import { Integrations } from '@/components/marketing/integrations';
import { MarketingPageHeader } from '@/components/marketing/marketing-page-header';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/integrations',
  title: 'Integrations',
  description:
    'Embed WebChat AI anywhere — plain script tags, React/Next.js, WordPress, any CMS, with a REST API for custom builds.',
});

export default function IntegrationsPage() {
  return (
    <>
      <MarketingPageHeader
        title="Integrations"
        description="Embed WebChat AI anywhere — plain script tags, React/Next.js, WordPress, any CMS, with a REST API for custom builds."
      />
      <Integrations />
      <FinalCta />
    </>
  );
}
