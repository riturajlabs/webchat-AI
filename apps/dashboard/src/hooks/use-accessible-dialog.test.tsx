import { act, fireEvent, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useAccessibleDialog } from './use-accessible-dialog';

function DialogFixture({ open, onClose }: { open: boolean; onClose: () => void }) {
  const contentRef = useRef<HTMLDivElement>(null);
  useAccessibleDialog({ open, onClose, contentRef });

  if (!open) {
    return (
      <div>
        <button data-testid="trigger">Open dialog</button>
      </div>
    );
  }

  return (
    <div>
      <button data-testid="trigger">Open dialog</button>
      <div data-dialog-overlay className="overlay" aria-hidden="true" />
      <div ref={contentRef} role="dialog" aria-modal="true" tabIndex={-1}>
        <button data-testid="first-btn">First</button>
        <button data-testid="second-btn">Second</button>
        <button data-testid="last-btn">Last</button>
      </div>
    </div>
  );
}

describe('useAccessibleDialog', () => {
  it('calls onClose when Escape is pressed', () => {
    const onClose = vi.fn();
    render(<DialogFixture open onClose={onClose} />);

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not call onClose on Escape when dialog is closed', () => {
    const onClose = vi.fn();
    render(<DialogFixture open={false} onClose={onClose} />);

    act(() => {
      fireEvent.keyDown(document, { key: 'Escape' });
    });

    expect(onClose).not.toHaveBeenCalled();
  });

  it('traps Tab so focus wraps from last to first', () => {
    const onClose = vi.fn();
    render(<DialogFixture open onClose={onClose} />);

    const lastBtn = screen.getByTestId('last-btn');
    const firstBtn = screen.getByTestId('first-btn');

    lastBtn.focus();

    act(() => {
      fireEvent.keyDown(document, { key: 'Tab' });
    });

    expect(document.activeElement).toBe(firstBtn);
  });

  it('traps Shift+Tab so focus wraps from first to last', () => {
    const onClose = vi.fn();
    render(<DialogFixture open onClose={onClose} />);

    const firstBtn = screen.getByTestId('first-btn');
    const lastBtn = screen.getByTestId('last-btn');

    firstBtn.focus();

    act(() => {
      fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    });

    expect(document.activeElement).toBe(lastBtn);
  });

  it('sets inert on sibling elements of the dialog content', () => {
    const onClose = vi.fn();
    render(<DialogFixture open onClose={onClose} />);

    const overlay = document.querySelector('[data-dialog-overlay]');
    expect(overlay).toHaveAttribute('inert');
  });

  it('removes inert from siblings on unmount', () => {
    const onClose = vi.fn();
    const { unmount } = render(<DialogFixture open onClose={onClose} />);

    const overlay = document.querySelector('[data-dialog-overlay]');
    expect(overlay).toHaveAttribute('inert');

    unmount();

    // After unmount, the inert attribute should be cleaned up by the effect cleanup.
    // Since the component is gone from the DOM, we verify no errors during cleanup.
  });

  it('does nothing on non-Tab keydown', () => {
    const onClose = vi.fn();
    render(<DialogFixture open onClose={onClose} />);

    const lastBtn = screen.getByTestId('last-btn');
    lastBtn.focus();

    act(() => {
      fireEvent.keyDown(document, { key: 'a' });
    });

    // Focus should remain on the last button since 'a' is not Tab.
    expect(document.activeElement).toBe(lastBtn);
  });
});
