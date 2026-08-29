import { Suspense } from 'react';

import { ResetPasswordForm } from '@/features/auth/reset-password-form';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/reset-password',
  title: 'Reset password',
  description: 'Choose a new password for your WebChat AI account.',
});

export default function ResetPasswordPage() {
  return (
    <>
      <h1 className="mb-4 font-sans text-xl font-semibold tracking-tight">Set a new password</h1>
      <Suspense fallback={null}>
        <ResetPasswordForm />
      </Suspense>
    </>
  );
}
