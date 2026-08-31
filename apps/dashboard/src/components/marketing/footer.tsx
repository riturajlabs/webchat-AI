'use client';

import Link from 'next/link';
import { Github, Globe, Instagram, Linkedin } from 'lucide-react';

import { useAuth } from '@/features/auth/auth-context';
import { getLandingDestination } from '@/lib/landing-navigation';

import { BrandMark } from './navbar';

const PRODUCT_LINKS = [
  { href: '/features', label: 'Features' },
  { href: '/how-it-works', label: 'How it works' },
  { href: '/integrations', label: 'Integrations' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/security', label: 'Security' },
];

const RESOURCE_DOC_LINKS = [
  { href: '/docs', label: 'Documentation' },
  { href: '/docs/api', label: 'API reference' },
];

const LEGAL_LINKS = [
  { href: '/privacy', label: 'Privacy Policy' },
  { href: '/terms', label: 'Terms of Service' },
];

const SOCIAL_LINKS = [
  {
    href: 'https://www.linkedin.com/in/riturajlabs/',
    label: 'LinkedIn',
    handle: 'riturajlabs',
    icon: Linkedin,
  },
  {
    href: 'https://github.com/riturajlabs',
    label: 'GitHub',
    handle: 'riturajlabs',
    icon: Github,
  },
  {
    href: 'https://www.instagram.com/riturajlabs/',
    label: 'Instagram',
    handle: 'riturajlabs',
    icon: Instagram,
  },
  {
    href: 'https://riturajlabs.vercel.app/',
    label: 'Portfolio',
    handle: 'riturajlabs',
    icon: Globe,
  },
];

function FooterColumn({
  title,
  links,
}: {
  title: string;
  links: readonly { href: string; label: string }[];
}) {
  return (
    <div>
      <h2 className="text-sm font-semibold">{title}</h2>
      <ul className="mt-3 flex flex-col gap-2">
        {links.map(({ href, label }) => (
          <li key={label}>
            <Link
              href={href}
              className="text-sm text-muted-foreground transition-colors hover:text-blue-600 dark:hover:text-blue-400"
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Footer() {
  const year = new Date().getFullYear();
  const { isAuthenticated, status } = useAuth();
  const isReady = status === 'ready';
  const signInHref = getLandingDestination('sign-in', isAuthenticated);
  const getStartedHref = getLandingDestination('get-started', isAuthenticated);

  return (
    <footer className="border-t border-border/60 bg-muted/30">
      <div className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="flex flex-col gap-3">
            <BrandMark />
            <p className="max-w-xs text-sm text-muted-foreground">
              Build intelligent AI assistants trained on your website content.
            </p>
            <div className="mt-3 border-t border-border/60 pt-4">
              <h3 className="text-sm font-semibold text-foreground">Connect with us</h3>
              <nav aria-label="Social media" className="mt-3 flex items-center gap-1.5">
                {SOCIAL_LINKS.map(({ href, label, icon: Icon }) => (
                  <a
                    key={label}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={label}
                    title={label}
                    className="flex size-9 items-center justify-center rounded-lg border border-transparent text-muted-foreground transition-colors hover:border-border hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Icon aria-hidden="true" className="size-4" />
                  </a>
                ))}
              </nav>
            </div>
          </div>
          <FooterColumn title="Product" links={PRODUCT_LINKS} />
          <div>
            <h2 className="text-sm font-semibold">Resources</h2>
            <ul className="mt-3 flex flex-col gap-2">
              {RESOURCE_DOC_LINKS.map(({ href, label }) => (
                <li key={label}>
                  <Link
                    href={href}
                    className="text-sm text-muted-foreground transition-colors hover:text-blue-600 dark:hover:text-blue-400"
                  >
                    {label}
                  </Link>
                </li>
              ))}
              {isReady ? (
                <>
                  <li>
                    <Link
                      href={signInHref}
                      className="text-sm text-muted-foreground transition-colors hover:text-blue-600 dark:hover:text-blue-400"
                    >
                      {isAuthenticated ? 'Dashboard' : 'Sign in'}
                    </Link>
                  </li>
                  <li>
                    <Link
                      href={getStartedHref}
                      className="text-sm text-muted-foreground transition-colors hover:text-blue-600 dark:hover:text-blue-400"
                    >
                      Get started
                    </Link>
                  </li>
                </>
              ) : null}
            </ul>
          </div>
          <FooterColumn title="Legal" links={LEGAL_LINKS} />
        </div>
        <div className="mt-10 border-t border-border/60 pt-6">
          <p className="text-sm text-muted-foreground">
            &copy; {year} WebChat AI. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
