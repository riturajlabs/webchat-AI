import type { Metadata } from 'next';
import { Suspense } from 'react';

import { VerifyEmailView } from '@/features/auth/verify-email-view';

export const metadata: Metadata = {
  title: 'Verify email',
};

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
