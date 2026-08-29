import { Suspense } from 'react';

import { VerifyEmailView } from '@/features/auth/verify-email-view';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/verify-email',
  title: 'Verify email',
  description: 'Verify your email address to activate your WebChat AI account.',
});

export default function VerifyEmailPage() {
  return (
    <>
      <h1 className="mb-4 font-sans text-xl font-semibold tracking-tight">Verify your email</h1>
      <Suspense fallback={null}>
        <VerifyEmailView />
      </Suspense>
    </>
  );
}
