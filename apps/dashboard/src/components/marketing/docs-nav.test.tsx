import { fireEvent, render, screen } from '@testing-library/react';
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

const mockUseAuth = vi.fn().mockReturnValue({
  isAuthenticated: false,
  status: 'ready',
});

vi.mock('@/features/auth/auth-context', () => ({
  useAuth: () => mockUseAuth(),
}));

import { DocsMobileNav, DocsSidebar } from './docs-nav';

describe('DocsMobileNav', () => {
  it('renders mobile trigger button with active document label and CTA', () => {
    render(<DocsMobileNav />);
    const trigger = screen.getByRole('button', { name: 'Toggle documentation navigation' });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Get Started' })).toBeInTheDocument();
  });

  it('toggles mobile drawer open on click and exposes search and links', () => {
    render(<DocsMobileNav />);
    const trigger = screen.getByRole('button', { name: 'Toggle documentation navigation' });
    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByPlaceholderText('Search docs...')).toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: 'Mobile Documentation Navigation' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Quickstart' })).toHaveAttribute(
      'href',
      '/docs/quickstart',
    );
    expect(screen.getByRole('link', { name: 'API reference' })).toHaveAttribute(
      'href',
      '/docs/api',
    );
  });

  it('filters navigation items in the mobile drawer', () => {
    render(<DocsMobileNav />);
    const trigger = screen.getByRole('button', { name: 'Toggle documentation navigation' });
    fireEvent.click(trigger);

    const searchInput = screen.getByPlaceholderText('Search docs...');
    fireEvent.change(searchInput, { target: { value: 'troubleshoot' } });

    expect(screen.getByRole('link', { name: 'Troubleshooting' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Quickstart' })).not.toBeInTheDocument();
  });
});

describe('DocsSidebar', () => {
  it('is hidden on mobile and visible on large screens', () => {
    const { container } = render(<DocsSidebar />);
    const aside = container.querySelector('aside') as HTMLElement;
    expect(aside).toHaveClass('hidden', 'lg:flex');
  });

  it('renders a filter input and all navigation groups', () => {
    render(<DocsSidebar />);
    expect(screen.getByPlaceholderText('Filter docs...')).toBeInTheDocument();
    expect(screen.getByText('Getting started')).toBeInTheDocument();
    expect(screen.getByText('Knowledge')).toBeInTheDocument();
    expect(screen.getByText('Widget')).toBeInTheDocument();
    expect(screen.getByText('Manage')).toBeInTheDocument();
    expect(screen.getByText('Developer')).toBeInTheDocument();
    expect(screen.getByText('Reference')).toBeInTheDocument();
  });

  it('renders all 15 documentation routes in the desktop sidebar', () => {
    render(<DocsSidebar />);
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/docs');
    expect(screen.getByRole('link', { name: 'Quickstart' })).toHaveAttribute(
      'href',
      '/docs/quickstart',
    );
    expect(screen.getByRole('link', { name: 'Knowledge sources' })).toHaveAttribute(
      'href',
      '/docs/knowledge-sources',
    );
    expect(screen.getByRole('link', { name: 'File uploads' })).toHaveAttribute(
      'href',
      '/docs/document-upload',
    );
    expect(screen.getByRole('link', { name: 'RAG & grounding' })).toHaveAttribute(
      'href',
      '/docs/rag-pipeline',
    );
    expect(screen.getByRole('link', { name: 'Embed' })).toHaveAttribute('href', '/docs/embed');
    expect(screen.getByRole('link', { name: 'Customization' })).toHaveAttribute(
      'href',
      '/docs/customization',
    );
    expect(screen.getByRole('link', { name: 'Configuration' })).toHaveAttribute(
      'href',
      '/docs/configuration',
    );
    expect(screen.getByRole('link', { name: 'Testing' })).toHaveAttribute('href', '/docs/testing');
    expect(screen.getByRole('link', { name: 'Conversations' })).toHaveAttribute(
      'href',
      '/docs/conversations',
    );
    expect(screen.getByRole('link', { name: 'Analytics & usage' })).toHaveAttribute(
      'href',
      '/docs/analytics',
    );
    expect(screen.getByRole('link', { name: 'API reference' })).toHaveAttribute(
      'href',
      '/docs/api',
    );
    expect(screen.getByRole('link', { name: 'Security' })).toHaveAttribute(
      'href',
      '/docs/security',
    );
    expect(screen.getByRole('link', { name: 'Troubleshooting' })).toHaveAttribute(
      'href',
      '/docs/troubleshooting',
    );
    expect(screen.getByRole('link', { name: 'Changelog' })).toHaveAttribute(
      'href',
      '/docs/changelog',
    );
  });

  it('renders auth-aware CTA button', () => {
    render(<DocsSidebar />);
    expect(screen.getByRole('link', { name: 'Get Started Free' })).toHaveAttribute(
      'href',
      '/signup',
    );
  });

  it('applies indented left padding to navigation links for hierarchy', () => {
    render(<DocsSidebar />);
    const link = screen.getByRole('link', { name: 'Overview' });
    expect(link).toHaveClass('pl-5', 'pr-3', 'py-1.5');
  });

  it('renders section headings with smaller uppercase styling', () => {
    render(<DocsSidebar />);
    const toggle = screen.getByRole('button', { name: 'Getting started' });
    expect(toggle).toHaveClass('px-2.5', 'text-[11px]', 'uppercase');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('link', { name: 'Overview' })).not.toBeInTheDocument();
  });
});

import { collectHeadings, DocsOnThisPage } from '@/features/docs/docs-client';
import { StepCard } from './docs-ui';

describe('DocsOnThisPage', () => {
  it('assigns deterministic unique ids to repeated heading text', () => {
    const root = document.createElement('main');
    root.innerHTML = '<h2>Install</h2><h2>Install</h2><h2 id="install">Install</h2>';

    const headings = collectHeadings(root);

    expect(headings.map((heading) => heading.id)).toEqual(['install', 'install-1', 'install-2']);
    expect(new Set(headings.map((heading) => heading.id)).size).toBe(3);
  });

  it('collects StepCard headings and renders on-this-page links', () => {
    render(
      <div id="docs-content">
        <StepCard step="01" id="create-account" title="Create your account">
          <p>Account setup</p>
        </StepCard>
        <StepCard step="02" id="choose-source" title="Choose your knowledge source">
          <p>Source selection</p>
        </StepCard>
        <DocsOnThisPage />
      </div>,
    );

    expect(screen.getByRole('navigation', { name: 'On this page' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Create your account' })).toHaveAttribute(
      'href',
      '#create-account',
    );
    expect(screen.getByRole('link', { name: 'Choose your knowledge source' })).toHaveAttribute(
      'href',
      '#choose-source',
    );
  });
});
