import { Suspense } from 'react';

import { AuthenticatedRedirect } from '@/features/auth/authenticated-redirect';
import { LoginForm } from '@/features/auth/login-form';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/login',
  title: 'Sign in',
  description: 'Sign in to your WebChat AI dashboard.',
});

export default function LoginPage() {
  return (
    <>
      <AuthenticatedRedirect />
      <h1 className="mb-4 font-sans text-xl font-semibold tracking-tight">Sign in</h1>
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </>
  );
}
