import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useAccessibleDialog } from './use-accessible-dialog';

function DialogFixture({
  open,
  onClose,
  preferredUnavailable = false,
}: {
  open: boolean;
  onClose: () => void;
  preferredUnavailable?: boolean;
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  useAccessibleDialog({ open, onClose, contentRef });

  return (
    <div>
      <button data-testid="trigger">Open dialog</button>
      {open ? (
        <>
          <div data-dialog-overlay className="overlay" aria-hidden="true" />
          <div ref={contentRef} role="dialog" aria-modal="true" tabIndex={-1}>
            {preferredUnavailable ? (
              <button data-autofocus data-testid="preferred-btn" disabled aria-label="Preferred" />
            ) : (
              <div
                data-autofocus
                data-testid="preferred-btn"
                tabIndex={-1}
                aria-label="Preferred"
              />
            )}
            <button data-testid="first-btn">First</button>
            <button data-testid="second-btn">Second</button>
            <button data-testid="last-btn">Last</button>
          </div>
        </>
      ) : null}
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

  it('does not mark background elements inert (isolation is via aria-modal + focus trap)', () => {
    const onClose = vi.fn();
    render(<DialogFixture open onClose={onClose} />);

    const trigger = screen.getByTestId('trigger');
    expect(trigger).not.toHaveAttribute('inert');
  });

  it('restores focus to the previously focused element when the dialog closes', async () => {
    const onClose = vi.fn();
    const { rerender } = render(<DialogFixture open={false} onClose={onClose} />);

    const trigger = screen.getByTestId('trigger');
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    rerender(<DialogFixture open onClose={onClose} />);
    await waitFor(() => expect(screen.getByTestId('preferred-btn')).toHaveFocus());

    rerender(<DialogFixture open={false} onClose={onClose} />);
    expect(screen.getByTestId('trigger')).toHaveFocus();
  });

  it('falls back to the first focusable element when data-autofocus cannot receive focus', async () => {
    const onClose = vi.fn();
    render(<DialogFixture open preferredUnavailable onClose={onClose} />);

    await waitFor(() => expect(screen.getByTestId('first-btn')).toHaveFocus());
  });

  it('focuses the preferred data-autofocus element on open', async () => {
    const onClose = vi.fn();
    render(<DialogFixture open onClose={onClose} />);

    await waitFor(() => expect(screen.getByTestId('preferred-btn')).toHaveFocus());
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
