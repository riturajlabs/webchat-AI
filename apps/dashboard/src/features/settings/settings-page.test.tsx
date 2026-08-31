import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import { useAuth } from '@/features/auth/auth-context';
import { clearSession } from '@/lib/session';

import { SettingsPage } from './settings-page';

vi.mock('@/lib/api', () => ({
  api: {
    delete: vi.fn(),
  },
}));

vi.mock('@/lib/session', () => ({
  clearSession: vi.fn(),
}));

vi.mock('next-themes', () => ({
  useTheme: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

import { useTheme } from 'next-themes';

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseTheme = vi.mocked(useTheme);
const mockedDelete = vi.mocked(api.delete);
const mockedClearSession = vi.mocked(clearSession);

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

function mockAuth() {
  mockedUseAuth.mockReturnValue({
    user: USER,
    status: 'ready',
  } as never);
}

function mockTheme() {
  mockedUseTheme.mockReturnValue({
    theme: 'system',
    setTheme: vi.fn(),
  } as never);
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth();
    mockTheme();
    mockedDelete.mockResolvedValue(undefined);
  });

  it('renders appearance and danger zone sections', () => {
    render(<SettingsPage />);

    expect(screen.getByRole('radiogroup', { name: 'Theme' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Light/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Dark/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /System/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete account' })).toBeInTheDocument();
  });

  it('changes theme when a radio option is selected', () => {
    const setTheme = vi.fn();
    mockedUseTheme.mockReturnValue({ theme: 'system', setTheme } as never);
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('radio', { name: /Dark/ }));
    expect(setTheme).toHaveBeenCalledWith('dark');
  });

  it('requires typing the account email to enable account deletion', () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));

    const confirmButton = screen.getByTestId('delete-account-confirm');
    expect(confirmButton).toBeDisabled();

    const input = screen.getByLabelText(/jane@example.com/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'wrong@example.com' } });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(input, { target: { value: USER.email } });
    expect(confirmButton).toBeEnabled();
  });

  it('deletes the account, clears the session and redirects to login', async () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));

    const input = screen.getByLabelText(/jane@example.com/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: USER.email } });
    fireEvent.click(screen.getByTestId('delete-account-confirm'));

    await waitFor(() => {
      expect(mockedDelete).toHaveBeenCalledWith('/api/auth/me');
    });
    expect(mockedClearSession).toHaveBeenCalled();
  });

  it('shows an inline error when deletion fails', async () => {
    mockedDelete.mockRejectedValue(new Error('Something went wrong'));
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Delete account' }));

    const input = screen.getByLabelText(/jane@example.com/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: USER.email } });
    fireEvent.click(screen.getByTestId('delete-account-confirm'));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong');
    });
  });
});
