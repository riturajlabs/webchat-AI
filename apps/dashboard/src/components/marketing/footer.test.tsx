import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn().mockReturnValue({
    isAuthenticated: false,
    status: 'ready',
  }),
}));

import { Footer } from './footer';

describe('Footer', () => {
  it('all footer column links have a generous touch target (inline-block py-1)', () => {
    const { container } = render(<Footer />);

    const links = Array.from(container.querySelectorAll('ul a'));
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link.className).toContain('py-1');
    }
  });

  it('renders a legal links column with Privacy Policy and Terms of Service', () => {
    render(<Footer />);
    expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute(
      'href',
      '/privacy',
    );
    expect(screen.getByRole('link', { name: 'Terms of Service' })).toHaveAttribute(
      'href',
      '/terms',
    );
  });

  it('renders column titles as semantic paragraph elements rather than h2/h3', () => {
    const { container } = render(<Footer />);
    expect(container.querySelectorAll('h2').length).toBe(0);
    expect(container.querySelectorAll('h3').length).toBe(0);
    expect(screen.getByText('Product')).toBeInTheDocument();
    expect(screen.getByText('Resources')).toBeInTheDocument();
    expect(screen.getByText('Legal')).toBeInTheDocument();
    expect(screen.getByText('Connect with us')).toBeInTheDocument();
  });
});
