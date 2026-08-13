import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/auth-context';

import { AdminGuard } from './admin-guard';

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

describe('AdminGuard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing while the session is being restored', () => {
    mockedUseAuth.mockReturnValue({ status: 'loading', user: null } as never);

    render(<AdminGuard>admin content</AdminGuard>);

    expect(screen.queryByText('admin content')).not.toBeInTheDocument();
    expect(screen.queryByText('Admin access required')).not.toBeInTheDocument();
  });

  it('shows an access-denied state for non-admins', () => {
    mockedUseAuth.mockReturnValue({ status: 'ready', user: { role: 'owner' } } as never);

    render(<AdminGuard>admin content</AdminGuard>);

    expect(screen.getByText('Admin access required')).toBeInTheDocument();
    expect(screen.queryByText('admin content')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back to dashboard' })).toBeInTheDocument();
  });

  it('renders children for admins', () => {
    mockedUseAuth.mockReturnValue({ status: 'ready', user: { role: 'admin' } } as never);

    render(<AdminGuard>admin content</AdminGuard>);

    expect(screen.getByText('admin content')).toBeInTheDocument();
    expect(screen.queryByText('Admin access required')).not.toBeInTheDocument();
  });
});
