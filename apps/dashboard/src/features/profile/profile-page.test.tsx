import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import { useAuth } from '@/features/auth/auth-context';

import { ProfilePage } from './profile-page';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);
const mockedPost = vi.mocked(api.post);

const UNVERIFIED_USER = {
  id: 'user-1',
  name: 'Jane Doe',
  email: 'jane@example.com',
  role: 'owner',
  email_verified: false,
  status: 'active',
  tenant_id: 'tenant-1',
  created_at: '2026-08-01T00:00:00Z',
};

const VERIFIED_USER = { ...UNVERIFIED_USER, email_verified: true };

describe('ProfilePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseAuth.mockReturnValue({ user: UNVERIFIED_USER, status: 'ready' } as never);
  });

  it('shows an unverified email status with verification buttons', () => {
    render(<ProfilePage />);

    expect(screen.getAllByText('❌ Email not verified').length).toBeGreaterThan(0);
    expect(screen.getByText('Pending Verification')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send verification email/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resend email/i })).toBeInTheDocument();
  });

  it('sends a verification email and shows the confirmation message', async () => {
    mockedPost.mockResolvedValue({ message: 'Verification email sent.' });

    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /send verification email/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith('/api/auth/resend-verification', {
        email: 'jane@example.com',
      });
    });
    expect(screen.getByRole('status').textContent).toBe(
      'Verification email sent. Please check your inbox.',
    );
  });

  it('resends the verification email from the secondary button', async () => {
    mockedPost.mockResolvedValue({ message: 'Verification email sent.' });

    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /resend email/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith('/api/auth/resend-verification', {
        email: 'jane@example.com',
      });
    });
    expect(screen.getByRole('status').textContent).toBe(
      'Verification email sent. Please check your inbox.',
    );
  });

  it('shows the error message when sending the verification email fails', async () => {
    mockedPost.mockRejectedValue(new Error('Failed to send.'));

    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /send verification email/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe('Failed to send.');
    });
  });

  it('shows a verified status and no buttons for a verified account', () => {
    mockedUseAuth.mockReturnValue({ user: VERIFIED_USER, status: 'ready' } as never);

    render(<ProfilePage />);

    expect(screen.getAllByText('✓ Email verified').length).toBeGreaterThan(0);
    expect(screen.getByText('Verified')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /send verification email/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /resend email/i })).not.toBeInTheDocument();
  });
});
