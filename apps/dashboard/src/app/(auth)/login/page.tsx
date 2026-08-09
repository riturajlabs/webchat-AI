import type { Metadata } from 'next';
import { Suspense } from 'react';

import { LoginForm } from '@/features/auth/login-form';

export const metadata: Metadata = {
  title: 'Sign in',
};

export default function LoginPage() {
  return (
    <>
      <h1 className="mb-4 font-sans text-xl font-semibold tracking-tight">Sign in</h1>
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </>
  );
}
