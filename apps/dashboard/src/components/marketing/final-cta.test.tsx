import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from '@/features/auth/auth-context';
import { FinalCta } from './final-cta';

const mockedUseAuth = vi.mocked(useAuth);

describe('FinalCta Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders "Sign up for free" linking to /signup when unauthenticated', () => {
    mockedUseAuth.mockReturnValue({
      isAuthenticated: false,
      status: 'ready',
      user: null,
      logout: vi.fn(),
    } as never);

    render(<FinalCta />);

    const ctaLink = screen.getByRole('link', { name: /Sign up for free/i });
    expect(ctaLink).toBeInTheDocument();
    expect(ctaLink).toHaveAttribute('href', '/signup');
  });

  it('renders "Dashboard" linking to /dashboard when authenticated', () => {
    mockedUseAuth.mockReturnValue({
      isAuthenticated: true,
      status: 'ready',
      user: { id: 'user-1', name: 'Alice' },
      logout: vi.fn(),
    } as never);

    render(<FinalCta />);

    const ctaLink = screen.getByRole('link', { name: /Dashboard/i });
    expect(ctaLink).toBeInTheDocument();
    expect(ctaLink).toHaveAttribute('href', '/dashboard');
    expect(screen.queryByRole('link', { name: /Sign up for free/i })).not.toBeInTheDocument();
  });
});
