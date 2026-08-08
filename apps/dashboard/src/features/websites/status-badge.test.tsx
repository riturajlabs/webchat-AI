import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StatusBadge } from './status-badge';

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="ready" />);
    expect(screen.getByText('ready')).toBeInTheDocument();
  });

  it.each([
    ['pending', 'bg-muted'],
    ['crawling', 'bg-blue-100'],
    ['processing', 'bg-amber-100'],
    ['ready', 'bg-green-100'],
    ['failed', 'bg-red-100'],
  ] as const)('applies the %s style', (status, className) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(status)).toHaveClass(className);
  });
});
