import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DocsPage } from './docs-page';

describe('DocsPage', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('renders all required documentation sections', () => {
    render(<DocsPage />);

    for (const title of [
      'Installation',
      'Script embedding',
      'Domain allowlist setup',
      'Configuration options',
      'Troubleshooting',
      'Security notes',
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it('uses production-style URLs and never localhost', () => {
    render(<DocsPage />);

    const bodyText = document.body.textContent ?? '';
    expect(bodyText).toContain('https://cdn.webchatai.example/webchat-widget.iife.min.js');
    expect(bodyText).toContain('https://api.webchatai.example/api/widget/v1');
    expect(bodyText.toLowerCase()).not.toContain('localhost');
    expect(bodyText.toLowerCase()).not.toContain('127.0.0.1');

    const dashboardLinks = screen.getAllByRole('link').map((link) => link.getAttribute('href'));
    expect(dashboardLinks.some((href) => href?.startsWith('https://app.webchatai.example'))).toBe(
      true,
    );
  });

  it('documents the embed script with the placeholder widget id', () => {
    render(<DocsPage />);

    expect(screen.getAllByText(/data-widget-id="YOUR_WIDGET_ID"/).length).toBeGreaterThan(0);
  });

  it('documents allowed domains matching rules', () => {
    render(<DocsPage />);

    expect(screen.getByText(/any origin \(not recommended\)/)).toBeInTheDocument();
    expect(screen.getAllByText(/403 Forbidden/).length).toBeGreaterThan(0);
  });

  it('copies a code sample and shows success feedback', async () => {
    render(<DocsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy script tag' }));

    const clipboard = vi.mocked(navigator.clipboard.writeText);
    expect(clipboard).toHaveBeenCalledWith(
      '<script src="https://cdn.webchatai.example/webchat-widget.iife.min.js" ' +
        'data-widget-id="YOUR_WIDGET_ID" defer></script>',
    );
    expect(await screen.findByRole('button', { name: 'Copied!' })).toBeInTheDocument();
  });
});
