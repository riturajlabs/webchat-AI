'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { useAuth } from '@/features/auth/auth-context';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const DEFAULT_REDIRECT = '/dashboard';

function appOrigin(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.location.origin;
}

/**
 * Resolve a post-login redirect into an app-internal path.
 *
 * Only same-app absolute paths that start with a single "/" are allowed. Every candidate is
 * run through the WHATWG URL parser against `window.location.origin` and accepted only when the
 * resolved URL's origin exactly matches the app origin. That single authority check (combined
 * with explicit rejection of encoded separators, backslashes, control characters and traversal
 * segments) is what closes open-redirect attacks: protocol-relative URLs, scheme-carrying
 * strings, backslash-host tricks and any crafted input that would make the browser resolve to a
 * foreign origin all fall back to {@link DEFAULT_REDIRECT}.
 */
export function getSafeRedirectTarget(raw: string | null): string {
  if (!raw || !raw.startsWith('/')) {
    return DEFAULT_REDIRECT;
  }
  if (raw.startsWith('//') || raw.startsWith('/\\')) {
    return DEFAULT_REDIRECT;
  }

  // Decode once so encoded separators/control characters are treated like their raw form.
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    return DEFAULT_REDIRECT;
  }
  if (decoded.includes('\\') || decoded.includes('\r') || decoded.includes('\n')) {
    return DEFAULT_REDIRECT;
  }
  if (!decoded.startsWith('/') || decoded.startsWith('//')) {
    return DEFAULT_REDIRECT;
  }
  // "https:evil.example", "javascript:alert(1)", "data:text/html,..." etc.
  if (/^[a-z][a-z0-9+.-]*:/i.test(decoded)) {
    return DEFAULT_REDIRECT;
  }

  // Origin check: the URL parser is the authority on how the browser would interpret the
  // string, so require the resolved origin to equal the app origin exactly.
  const origin = appOrigin();
  if (origin && new URL(decoded, origin).origin !== origin) {
    return DEFAULT_REDIRECT;
  }

  // Reject traversal segments so redirects stay inside the app root.
  if (decoded.split('/').some((segment) => segment === '..' || segment === '.')) {
    return DEFAULT_REDIRECT;
  }

  return raw;
}

export function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get('redirect') ?? '/dashboard';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !password || isPending) {
      return;
    }
    setIsPending(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace(getSafeRedirectTarget(redirectTo));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to sign in.');
    } finally {
      setIsPending(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="login-email">Email</Label>
        <Input
          id="login-email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <Label htmlFor="login-password">Password</Label>
          <Link
            href="/forgot-password"
            className="text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            Forgot password?
          </Link>
        </div>
        <Input
          id="login-password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="••••••••"
        />
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <Button type="submit" disabled={isPending}>
        {isPending ? 'Signing in…' : 'Sign in'}
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        No account yet?{' '}
        <Link
          href="/signup"
          className="font-medium text-foreground underline-offset-4 hover:underline"
        >
          Create one
        </Link>
      </p>
    </form>
  );
}
