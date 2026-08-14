import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LoginForm } from './login-form';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/features/auth/auth-context';

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseRouter = vi.mocked(useRouter);
const mockedUseSearchParams = vi.mocked(useSearchParams);

describe('LoginForm', () => {
  const login = vi.fn();
  const replace = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseAuth.mockReturnValue({ login } as never);
    mockedUseRouter.mockReturnValue({ replace } as never);
    mockedUseSearchParams.mockReturnValue({ get: vi.fn(() => null) } as never);
  });

  function fill() {
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'jane@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Str0ngPass!123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
  }

  it('logs in an unverified user without blocking (login allowed)', async () => {
    login.mockResolvedValue({ email_verified: false });

    render(<LoginForm />);
    fill();

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith('jane@example.com', 'Str0ngPass!123');
    });
    expect(replace).toHaveBeenCalledWith('/');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('logs in a verified user normally', async () => {
    login.mockResolvedValue({ email_verified: true });

    render(<LoginForm />);
    fill();

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the error message when login fails', async () => {
    login.mockRejectedValue(new Error('Invalid email or password.'));

    render(<LoginForm />);
    fill();

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe('Invalid email or password.');
    });
    expect(replace).not.toHaveBeenCalled();
  });
});
