import type { Metadata } from 'next';

import { SignupForm } from '@/features/auth/signup-form';

export const metadata: Metadata = {
  title: 'Create account',
};

export default function SignupPage() {
  return (
    <>
      <h1 className="mb-4 font-sans text-xl font-semibold tracking-tight">Create account</h1>
      <SignupForm />
    </>
  );
}
