import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Avatar } from './avatar';

/** The avatar <img> is decorative (alt="") and not in the a11y tree, so we
 * query it via the DOM container. */
function imgOf(container: HTMLElement): HTMLImageElement | null {
  return container.querySelector('img');
}

describe('Avatar', () => {
  it('renders initials when no photo exists', () => {
    const { container } = render(<Avatar name="Ritu Raj" className="h-8 w-8" />);
    expect(screen.getByText('RR')).toBeInTheDocument();
    expect(imgOf(container)).toBeNull();
  });

  it('renders the profile photo when present', () => {
    const { container } = render(
      <Avatar name="Ritu Raj" avatarUrl="data:image/png;base64,AAA" className="h-8 w-8" />,
    );
    const img = imgOf(container);
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute('src', 'data:image/png;base64,AAA');
    expect(screen.queryByText('RR')).not.toBeInTheDocument();
  });

  it('falls back to initials when the photo fails to load', () => {
    const { container } = render(
      <Avatar name="Ritu Raj" avatarUrl="https://broken.example/x.png" className="h-8 w-8" />,
    );
    const img = imgOf(container);
    expect(img).not.toBeNull();
    fireEvent.error(img as HTMLImageElement);
    expect(imgOf(container)).toBeNull();
    expect(screen.getByText('RR')).toBeInTheDocument();
  });
});
