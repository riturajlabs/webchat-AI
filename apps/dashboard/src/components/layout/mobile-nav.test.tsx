import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/auth-context';

import { MobileNav } from './mobile-nav';

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn(),
}));

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    onClick,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  }) => (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        onClick?.(event);
      }}
      {...props}
    >
      {children}
    </a>
  ),
}));

import { usePathname } from 'next/navigation';

const mockedUsePathname = vi.mocked(usePathname);
const mockedUseAuth = vi.mocked(useAuth);

describe('MobileNav', () => {
  beforeEach(() => {
    mockedUsePathname.mockReturnValue('/');
    mockedUseAuth.mockReturnValue({
      user: { role: 'owner' },
    } as never);
  });

  afterEach(() => {
    vi.clearAllMocks();
    document.body.style.overflow = '';
  });

  it('renders the hamburger trigger hidden on desktop', () => {
    render(<MobileNav />);
    const trigger = screen.getByRole('button', { name: 'Open navigation' });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveClass('md:hidden');
  });

  it('opens the drawer and shows navigation items', () => {
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));

    const dialog = screen.getByRole('dialog', { name: 'Navigation' });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Mobile navigation' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Websites' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Conversations' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Analytics' })).toBeInTheDocument();
  });

  it('closes the drawer when a navigation item is clicked', () => {
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(screen.getByRole('dialog', { name: 'Navigation' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('link', { name: 'Websites' }));

    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
  });

  it('closes the drawer when Escape is pressed', () => {
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(screen.getByRole('dialog', { name: 'Navigation' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
  });

  it('closes the drawer when the close button is clicked', () => {
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));

    fireEvent.click(screen.getByRole('button', { name: 'Close navigation' }));

    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument();
  });

  it('highlights the active route', () => {
    mockedUsePathname.mockReturnValue('/websites');
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));

    expect(screen.getByRole('link', { name: 'Websites' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Dashboard' })).not.toHaveAttribute('aria-current');
  });

  it('renders navigation links to their destinations', () => {
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));

    expect(screen.getByRole('link', { name: 'Websites' })).toHaveAttribute('href', '/websites');
    expect(screen.getByRole('link', { name: 'API Keys' })).toHaveAttribute('href', '/api-keys');
  });

  it('hides the Admin link for non-admin roles', () => {
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));

    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument();
  });

  it('shows the Admin link for super admins', () => {
    mockedUseAuth.mockReturnValue({
      user: { role: 'super_admin' },
    } as never);
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));

    expect(screen.getByRole('link', { name: 'Admin' })).toHaveAttribute('href', '/admin');
  });

  it('restores focus to the trigger after closing', () => {
    render(<MobileNav />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveFocus();
  });
});
