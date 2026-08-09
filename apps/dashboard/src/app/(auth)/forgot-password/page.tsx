import type { Metadata } from 'next';

import { ForgotPasswordForm } from '@/features/auth/forgot-password-form';

export const metadata: Metadata = {
  title: 'Forgot password',
};

export default function ForgotPasswordPage() {
  return (
    <>
      <h1 className="mb-4 font-sans text-xl font-semibold tracking-tight">Reset your password</h1>
      <p className="mb-4 text-sm text-muted-foreground">
        Enter your account email and we will send you a reset link.
      </p>
      <ForgotPasswordForm />
    </>
  );
}
