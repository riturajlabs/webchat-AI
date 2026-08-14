import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SignupForm } from './signup-form';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

import { useRouter } from 'next/navigation';
import { useAuth } from '@/features/auth/auth-context';

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseRouter = vi.mocked(useRouter);

describe('SignupForm', () => {
  const register = vi.fn();
  const replace = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseAuth.mockReturnValue({ register } as never);
    mockedUseRouter.mockReturnValue({ replace } as never);
  });

  function fill(email: string) {
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Jane Doe' } });
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Str0ngPass!123' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
  }

  function submitForm(container: HTMLElement) {
    // fireEvent.submit dispatches the submit event directly, bypassing jsdom's
    // native constraint validation (which would otherwise swallow clearly
    // invalid emails before our client-side check can run).
    fireEvent.submit(container.querySelector('form')!);
  }

  it.each(['abc', 'test@', 'test@gmail', '@gmail.com'])(
    'rejects invalid email %s on the client without calling the API',
    (email) => {
      const { container } = render(<SignupForm />);
      fill(email);
      submitForm(container);

      expect(screen.getByRole('alert').textContent).toBe('Please enter a valid email address.');
      expect(register).not.toHaveBeenCalled();
      expect(replace).not.toHaveBeenCalled();
    },
  );

  it('submits a valid email (trimmed, lowercased) and redirects to the dashboard', async () => {
    register.mockResolvedValue({ email_verified: false });

    render(<SignupForm />);
    fill('User@Gmail.com ');

    await waitFor(() => {
      expect(register).toHaveBeenCalledWith('Jane Doe', 'user@gmail.com', 'Str0ngPass!123');
    });
    expect(replace).toHaveBeenCalledWith('/');
  });

  it('shows the backend error message when signup fails', async () => {
    register.mockRejectedValue(new Error('An account with this email already exists.'));

    render(<SignupForm />);
    fill('jane@example.com');

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe(
        'An account with this email already exists.',
      );
    });
    expect(replace).not.toHaveBeenCalled();
  });
});
