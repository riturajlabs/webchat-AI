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
const mockedPatch = vi.mocked(api.patch);

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

function mockUser(user: typeof UNVERIFIED_USER) {
  const updateUser = vi.fn();
  mockedUseAuth.mockReturnValue({
    user,
    status: 'ready',
    updateUser,
  } as never);
  return { updateUser } as { updateUser: ReturnType<typeof vi.fn> };
}

describe('ProfilePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser(UNVERIFIED_USER);
  });

  it('shows account information for the signed-in user', () => {
    render(<ProfilePage />);

    expect(screen.getAllByText('Jane Doe').length).toBeGreaterThan(0);
    expect(screen.getAllByText('jane@example.com').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Owner').length).toBeGreaterThan(0);
    expect(screen.getByText('Member since')).toBeInTheDocument();
    expect(screen.getAllByText(/2026/).length).toBeGreaterThan(0);
  });

  it('shows an initials avatar fallback when no photo is set', () => {
    render(<ProfilePage />);

    expect(screen.getByText('JD')).toBeInTheDocument();
  });

  it('renders initials from a single word name', () => {
    mockUser({ ...UNVERIFIED_USER, name: 'Jane' });
    render(<ProfilePage />);
    expect(screen.getByText('J')).toBeInTheDocument();
  });

  it('shows a Verify email button for an unverified account', () => {
    render(<ProfilePage />);

    expect(screen.getByRole('button', { name: /verify email/i })).toBeInTheDocument();
  });

  it('sends a verification email and shows the confirmation message', async () => {
    mockedPost.mockResolvedValue({ message: 'Verification email sent.' });

    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /verify email/i }));

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
    fireEvent.click(screen.getByRole('button', { name: /verify email/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe('Failed to send.');
    });
  });

  it('shows a disabled Verified state for a verified account', () => {
    mockUser(VERIFIED_USER);
    render(<ProfilePage />);

    expect(screen.getByText('Verified')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /verify email/i })).not.toBeInTheDocument();
  });

  it('enters edit mode and cancels back to the original values', () => {
    render(<ProfilePage />);

    fireEvent.click(screen.getByRole('button', { name: /edit profile/i }));
    const input = screen.getByLabelText('Name') as HTMLInputElement;
    expect(input.value).toBe('Jane Doe');

    fireEvent.change(input, { target: { value: 'John Smith' } });
    expect(input.value).toBe('John Smith');

    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    expect(screen.getAllByText('Jane Doe').length).toBeGreaterThan(0);
  });

  it('saves an edited name and updates the profile', async () => {
    const { updateUser } = mockUser(UNVERIFIED_USER);
    mockedPatch.mockResolvedValue({ ...UNVERIFIED_USER, name: 'John Smith' });

    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /edit profile/i }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'John Smith' } });

    const saveButton = screen.getByRole('button', { name: /save changes/i });
    expect(saveButton).not.toBeDisabled();
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockedPatch).toHaveBeenCalledWith('/api/auth/me', { name: 'John Smith' });
    });
    await waitFor(() => {
      expect(updateUser).toHaveBeenCalledWith({
        name: 'John Smith',
        avatar_url: null,
      });
    });
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
  });

  it('disables save when nothing has changed', () => {
    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /edit profile/i }));

    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('shows an inline error when the trimmed name is empty', async () => {
    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /edit profile/i }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '   ' } });

    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe('Name cannot be empty.');
    });
    expect(mockedPatch).not.toHaveBeenCalled();
  });

  it('shows an inline error when the name is too short', () => {
    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /edit profile/i }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'A' } });

    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

    expect(screen.getByRole('alert').textContent).toBe('Name must be at least 2 characters.');
  });

  it('keeps the email read-only in edit mode', () => {
    render(<ProfilePage />);
    fireEvent.click(screen.getByRole('button', { name: /edit profile/i }));

    expect(screen.getAllByText('jane@example.com').length).toBeGreaterThan(0);
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument();
  });
});
