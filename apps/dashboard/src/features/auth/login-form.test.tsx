import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LoginForm, getSafeRedirectTarget } from './login-form';

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
    expect(replace).toHaveBeenCalledWith('/dashboard');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('logs in a verified user normally', async () => {
    login.mockResolvedValue({ email_verified: true });

    render(<LoginForm />);
    fill();

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
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

  it('falls back to /dashboard when an unsafe redirect is injected', async () => {
    mockedUseSearchParams.mockReturnValue({ get: vi.fn(() => '//evil.example') } as never);
    login.mockResolvedValue({ email_verified: false });

    render(<LoginForm />);
    fill();

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(login).toHaveBeenCalledWith('jane@example.com', 'Str0ngPass!123');
  });

  it('honours a safe same-app redirect parameter', async () => {
    mockedUseSearchParams.mockReturnValue({ get: vi.fn(() => '/widget/setup') } as never);
    login.mockResolvedValue({ email_verified: false });

    render(<LoginForm />);
    fill();

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/widget/setup'));
  });
});

describe('getSafeRedirectTarget', () => {
  it('keeps plain same-app paths', () => {
    expect(getSafeRedirectTarget('/dashboard')).toBe('/dashboard');
    expect(getSafeRedirectTarget('/widget/setup?tab=script')).toBe('/widget/setup?tab=script');
    expect(getSafeRedirectTarget('/docs#intro')).toBe('/docs#intro');
  });

  it('falls back for empty and non-path values', () => {
    expect(getSafeRedirectTarget(null)).toBe('/dashboard');
    expect(getSafeRedirectTarget('')).toBe('/dashboard');
    expect(getSafeRedirectTarget('dashboard')).toBe('/dashboard');
  });

  it('blocks protocol-relative URLs', () => {
    expect(getSafeRedirectTarget('//evil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('///evil.example')).toBe('/dashboard');
  });

  it('blocks backslash tricks', () => {
    expect(getSafeRedirectTarget('/\\evil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('\\evil.example')).toBe('/dashboard');
  });

  it('blocks encoded separators and control characters', () => {
    expect(getSafeRedirectTarget('%2F%2Fevil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('/%2Fevil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('/%5Cevil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('/%0D%0Aevil.example')).toBe('/dashboard');
  });

  it('blocks scheme-carrying strings', () => {
    expect(getSafeRedirectTarget('https://evil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('http:evil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('https:evil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('javascript:alert(1)')).toBe('/dashboard');
    expect(getSafeRedirectTarget('data:text/html,<script>alert(1)</script>')).toBe('/dashboard');
  });

  it('requires the resolved URL to keep the current app origin', () => {
    const origin = window.location.origin;
    // A plain relative path must resolve to the app origin and pass through…
    expect(new URL('/billing', origin).origin).toBe(origin);
    expect(getSafeRedirectTarget('/billing')).toBe('/billing');
    // …while anything that would make the URL parser escape the app origin is refused.
    expect(getSafeRedirectTarget('//evil.example')).toBe('/dashboard');
    expect(getSafeRedirectTarget('/%5Cevil.example')).toBe('/dashboard');
  });

  it('blocks path traversal back to a valid-looking route', () => {
    expect(getSafeRedirectTarget('/billing/../evil')).toBe('/dashboard');
    expect(getSafeRedirectTarget('%2e%2e/billing')).toBe('/dashboard');
  });
});
