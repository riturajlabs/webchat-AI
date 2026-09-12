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

import { Pricing } from './pricing';

describe('Pricing', () => {
  it('shows 4 pricing plans in a 2-column tablet / 4-column desktop grid', () => {
    const { container } = render(<Pricing />);
    const grid = container.querySelector('#pricing .grid') as HTMLElement;

    expect(grid).toHaveClass('md:grid-cols-2', 'lg:grid-cols-4');
    expect(
      screen.getAllByRole('link').filter((el) => el.closest('#pricing')).length,
    ).toBeGreaterThanOrEqual(4);
  });

  it('has an accessible section heading', () => {
    render(<Pricing />);
    expect(
      screen.getByRole('heading', { name: 'Simple, transparent pricing' }),
    ).toBeInTheDocument();
  });
});
