import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/auth-context';
import { AuthGuard } from './auth-guard';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

import { useRouter } from 'next/navigation';

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseRouter = vi.mocked(useRouter);

describe('AuthGuard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseRouter.mockReturnValue({ replace: vi.fn() } as never);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading indicator while the session is being restored', () => {
    mockedUseAuth.mockReturnValue({
      isAuthenticated: false,
      status: 'loading',
    } as never);

    render(<AuthGuard>content</AuthGuard>);

    expect(screen.getByRole('status', { name: 'Loading page' })).toBeInTheDocument();
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('redirects to /login with the current path when unauthenticated', () => {
    const replace = vi.fn();
    mockedUseRouter.mockReturnValue({ replace } as never);
    mockedUseAuth.mockReturnValue({
      isAuthenticated: false,
      status: 'ready',
    } as never);

    render(<AuthGuard>content</AuthGuard>);

    expect(replace).toHaveBeenCalledWith('/login?redirect=%2F');
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    mockedUseAuth.mockReturnValue({
      isAuthenticated: true,
      status: 'ready',
    } as never);

    render(<AuthGuard>content</AuthGuard>);

    expect(screen.getByText('content')).toBeInTheDocument();
  });
});
