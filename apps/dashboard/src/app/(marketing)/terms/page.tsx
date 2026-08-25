import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description: 'The terms that govern your use of the WebChat AI platform.',
};

export default function TermsPage() {
  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-16 md:px-6 md:py-24">
      <h1 className="font-sans text-3xl font-bold tracking-tight">Terms of Service</h1>
      <p className="mt-2 text-sm text-muted-foreground">Last updated: August 2026</p>
      <div className="mt-8 flex flex-col gap-4 text-sm text-muted-foreground [&_h2]:text-base [&_h2]:font-medium [&_h2]:text-foreground">
        <p>
          This summary describes the ground rules for using WebChat AI. The full agreement will be
          published before general availability.
        </p>
        <h2>Your account</h2>
        <p>
          You are responsible for activity under your account and for keeping your credentials safe.
          You must have the right to index and publish content for every website you register.
        </p>
        <h2>Acceptable use</h2>
        <p>
          Only index content you own or are authorized to use. Do not use the service to generate
          misleading, unlawful, or harmful material, and do not attempt to disrupt other tenants of
          the platform.
        </p>
        <h2>Service availability</h2>
        <p>
          The platform is offered on a beta basis while plans are finalized; features and quotas may
          change. Usage limits for each tier are shown in the dashboard before you incur them.
        </p>
      </div>
    </div>
  );
}
