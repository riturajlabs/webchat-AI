import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/privacy',
  title: 'Privacy Policy',
  description: 'How WebChat AI handles your data and the data of your website visitors.',
});

export default function PrivacyPage() {
  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-16 md:px-6 md:py-24">
      <h1 className="font-sans text-3xl font-bold tracking-tight">Privacy Policy</h1>
      <p className="mt-2 text-sm text-muted-foreground">Last updated: August 2026</p>
      <div className="mt-8 flex flex-col gap-4 text-sm text-muted-foreground [&_h2]:text-base [&_h2]:font-medium [&_h2]:text-foreground">
        <p>
          This summary describes how WebChat AI processes personal data. The full policy will be
          published before general availability.
        </p>
        <h2>Data we process</h2>
        <p>
          Account details you provide (name, email), the content of websites you register for
          indexing, configuration of your chat widgets, and conversations end users have with your
          assistants. Access tokens are kept in memory only; refresh tokens are stored in httpOnly
          cookies and are never readable by scripts on the page.
        </p>
        <h2>How content is used</h2>
        <p>
          Website content you register is used to build a per-tenant knowledge base so your
          assistant can answer questions about that site. We do not sell your data or use it to
          advertise to third parties.
        </p>
        <h2>Your choices</h2>
        <p>
          You can remove registered websites, delete indexed content, disable individual widgets,
          and close your account at any time from the dashboard. Questions? Contact us through the
          in-app support channel once your account is active.
        </p>
      </div>
    </div>
  );
}
