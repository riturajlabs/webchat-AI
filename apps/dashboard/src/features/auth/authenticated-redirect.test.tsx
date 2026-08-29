import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthenticatedRedirect } from './authenticated-redirect';

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

describe('AuthenticatedRedirect', () => {
  const replace = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseRouter.mockReturnValue({ replace } as never);
  });

  it('redirects a ready, authenticated user to the dashboard', () => {
    mockedUseAuth.mockReturnValue({ status: 'ready', isAuthenticated: true } as never);
    render(<AuthenticatedRedirect />);
    expect(replace).toHaveBeenCalledWith('/dashboard');
  });

  it('does not redirect while auth is still resolving', () => {
    mockedUseAuth.mockReturnValue({ status: 'loading', isAuthenticated: false } as never);
    render(<AuthenticatedRedirect />);
    expect(replace).not.toHaveBeenCalled();
  });

  it('does not redirect guests', () => {
    mockedUseAuth.mockReturnValue({ status: 'ready', isAuthenticated: false } as never);
    render(<AuthenticatedRedirect />);
    expect(replace).not.toHaveBeenCalled();
  });
});
