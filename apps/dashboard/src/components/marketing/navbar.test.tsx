import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Navbar } from './navbar';

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

vi.mock('./mobile-menu', () => ({
  MobileMenu: () => null,
}));

import { useAuth } from '@/features/auth/auth-context';

const mockedUseAuth = vi.mocked(useAuth);

const USER = {
  id: 'user-1',
  name: 'Jane Doe',
  email: 'jane@example.com',
  role: 'owner',
  email_verified: true,
  status: 'active',
  tenant_id: 'tenant-1',
  created_at: '2026-08-01T00:00:00Z',
};

function mockAuth(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  mockedUseAuth.mockReturnValue({
    user: USER,
    status: 'ready',
    isAuthenticated: true,
    logout: vi.fn(),
    ...overrides,
  } as never);
}

describe('Navbar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the profile photo in the account menu when the user has an avatar', () => {
    mockAuth({ user: { ...USER, avatar_url: 'data:image/png;base64,AA==' } });
    const { container } = render(<Navbar />);

    const img = container.querySelector('img[src^="data:image"]');
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('src', 'data:image/png;base64,AA==');
  });

  it('falls back to initials when the user has no avatar', () => {
    mockAuth({ user: { ...USER, avatar_url: null } });
    const { container } = render(<Navbar />);

    expect(container.querySelector('img[src^="data:image"]')).toBeNull();
    const badge = container.querySelector('span[aria-hidden="true"]');
    expect(badge?.textContent).toBe('JD');
  });

  it('shows sign-in actions for anonymous visitors', () => {
    mockAuth({ user: null, isAuthenticated: false } as never);
    render(<Navbar />);

    expect(screen.getByRole('link', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Get Started' })).toBeInTheDocument();
  });
});
