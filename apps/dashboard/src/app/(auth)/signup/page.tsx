import { AuthenticatedRedirect } from '@/features/auth/authenticated-redirect';
import { SignupForm } from '@/features/auth/signup-form';
import { seoPage } from '@/lib/seo';

export const metadata = seoPage({
  path: '/signup',
  title: 'Create account',
  description: 'Create a free WebChat AI account and put an AI assistant on your website.',
});

export default function SignupPage() {
  return (
    <>
      <AuthenticatedRedirect />
      <h1 className="mb-4 font-sans text-xl font-semibold tracking-tight">Create account</h1>
      <SignupForm />
    </>
  );
}
