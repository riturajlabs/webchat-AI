import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/auth-context';

import { VerificationReminder } from './verification-reminder';

vi.mock('next/navigation', () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

const UNVERIFIED_USER = { id: 'user-1', email_verified: false };

describe('VerificationReminder', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('shows the unverified warning with a link to verify', () => {
    mockedUseAuth.mockReturnValue({ user: UNVERIFIED_USER } as never);

    render(<VerificationReminder />);

    expect(
      screen.getByText('Your email is not verified. Please verify your email.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Verify Email' })).toHaveAttribute('href', '/profile');
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument();
  });

  it('hides the banner and persists the dismissal for the current user', () => {
    mockedUseAuth.mockReturnValue({ user: UNVERIFIED_USER } as never);

    render(<VerificationReminder />);
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(screen.queryByText(/not verified/i)).not.toBeInTheDocument();
    expect(window.localStorage.getItem('webchat:verification-banner-dismissed:user-1')).toBe('1');
  });

  it('stays hidden when the same user dismissed it in a previous session', () => {
    window.localStorage.setItem('webchat:verification-banner-dismissed:user-1', '1');
    mockedUseAuth.mockReturnValue({ user: UNVERIFIED_USER } as never);

    render(<VerificationReminder />);

    expect(screen.queryByText(/not verified/i)).not.toBeInTheDocument();
  });

  it('shows the banner for another user who has not dismissed it', () => {
    window.localStorage.setItem('webchat:verification-banner-dismissed:user-1', '1');
    mockedUseAuth.mockReturnValue({ user: { id: 'user-2', email_verified: false } } as never);

    render(<VerificationReminder />);

    expect(screen.getByText(/not verified/i)).toBeInTheDocument();
  });

  it('renders nothing for a verified account', () => {
    mockedUseAuth.mockReturnValue({ user: { id: 'user-1', email_verified: true } } as never);

    render(<VerificationReminder />);

    expect(screen.queryByText(/not verified/i)).not.toBeInTheDocument();
  });

  it('renders nothing when there is no signed-in user', () => {
    mockedUseAuth.mockReturnValue({ user: null } as never);

    render(<VerificationReminder />);

    expect(screen.queryByText(/not verified/i)).not.toBeInTheDocument();
  });
});
