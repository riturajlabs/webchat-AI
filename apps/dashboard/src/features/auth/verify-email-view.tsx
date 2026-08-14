'use client';

import { useSearchParams } from 'next/navigation';

import { ResendVerificationForm } from './resend-verification-form';
import { VerifyEmailForm } from './verify-email-form';

/**
 * Route the /verify-email page between the two email-verification states:
 * a `?token=` (email link) runs the verification; otherwise the resend form
 * is shown (signup redirect / stale unverified session).
 */
export function VerifyEmailView() {
  const searchParams = useSearchParams();
  return searchParams.get('token') ? <VerifyEmailForm /> : <ResendVerificationForm />;
}
