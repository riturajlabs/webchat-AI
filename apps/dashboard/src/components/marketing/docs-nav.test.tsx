import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  usePathname: () => '/docs',
}));

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: vi.fn().mockReturnValue({
    isAuthenticated: false,
    status: 'ready',
  }),
}));

import { DocsMobileNav, DocsSidebar } from './docs-nav';

const NAV_MASK_CLASS =
  'max-[750px]:[mask-image:linear-gradient(to_right,black_calc(100%_-_20px),transparent)]';

describe('DocsMobileNav', () => {
  it('has horizontal scroll with an overflow fade affordance', () => {
    render(<DocsMobileNav />);
    const nav = screen.getByRole('navigation', { name: 'Documentation' });
    expect(nav).toHaveClass('overflow-x-auto');
    expect(nav.className).toContain(NAV_MASK_CLASS);
  });

  it('renders documentation navigation links and a CTA', () => {
    render(<DocsMobileNav />);
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/docs');
    expect(screen.getByRole('link', { name: /Get Started/ })).toBeInTheDocument();
  });
});

describe('DocsSidebar', () => {
  it('is hidden on mobile and visible on large screens', () => {
    const { container } = render(<DocsSidebar />);
    const aside = container.querySelector('aside') as HTMLElement;
    expect(aside).toHaveClass('hidden', 'lg:flex');
  });

  it('renders a search input', () => {
    render(<DocsSidebar />);
    expect(screen.getByPlaceholderText('Search docs…')).toBeInTheDocument();
  });
});
