import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';

import { ResendVerificationForm } from './resend-verification-form';

vi.mock('next/navigation', () => ({
  useSearchParams: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import { useSearchParams } from 'next/navigation';

const mockedUseSearchParams = vi.mocked(useSearchParams);
const mockedPost = vi.mocked(api.post);

function mockSearchParams(email: string | null) {
  mockedUseSearchParams.mockReturnValue({
    get: vi.fn(() => email),
  } as never);
}

describe('ResendVerificationForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams(null);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('pre-fills the email from the ?email= query param', () => {
    mockSearchParams('jane@example.com');

    render(<ResendVerificationForm />);

    expect(screen.getByLabelText('Email')).toHaveValue('jane@example.com');
  });

  it('posts the trimmed lowercase email and shows the generic message', async () => {
    mockedPost.mockResolvedValue({
      message: 'If that address is registered, a fresh verification link is on its way.',
    });

    render(<ResendVerificationForm />);

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'Jane@Example.com ' },
    });
    fireEvent.click(screen.getByRole('button', { name: /resend verification link/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith('/api/auth/resend-verification', {
        email: 'jane@example.com',
      });
    });
    expect(screen.getByRole('status').textContent).toContain('fresh verification link');
  });

  it('shows the error message when the request fails', async () => {
    mockedPost.mockRejectedValue(new Error('Network error'));

    render(<ResendVerificationForm />);

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'jane@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: /resend verification link/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe('Network error');
    });
  });

  it('does not submit an empty email', () => {
    render(<ResendVerificationForm />);

    fireEvent.click(screen.getByRole('button', { name: /resend verification link/i }));

    expect(mockedPost).not.toHaveBeenCalled();
  });
});
