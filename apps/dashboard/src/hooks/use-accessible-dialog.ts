'use client';

import { useEffect, useRef } from 'react';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Returns all focusable elements within a container, in DOM order.
 */
function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR));
}

interface UseAccessibleDialogOptions {
  /** Whether the dialog is currently open. */
  open: boolean;
  /** Called when the dialog should close (e.g., Escape key, backdrop click). */
  onClose: () => void;
  /** The dialog content element ref (the panel, not the overlay). */
  contentRef: React.RefObject<HTMLElement | null>;
}

/**
 * Implements WCAG 2.1 modal dialog behavior:
 *
 * - **Focus trapping**: Tab/Shift+Tab cycles within the dialog.
 * - **Escape key**: Calls `onClose`.
 * - **Focus restoration**: Returns focus to the element that had it before the dialog opened.
 * - **Auto-focus**: Moves focus to the element marked `[data-autofocus]` inside the
 *   dialog, falling back to the first focusable element when the preferred element
 *   cannot receive focus.
 *
 * Background isolation is provided by the dialog markup: consumers set
 * `aria-modal="true"` so assistive technology treats the rest of the page as
 * background, and the focus trap keeps keyboard focus inside the dialog.
 *
 * All behavior is implemented with native DOM APIs — no extra dependencies.
 */
export function useAccessibleDialog({ open, onClose, contentRef }: UseAccessibleDialogOptions) {
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // --- Escape key handler ---
  useEffect(() => {
    if (!open) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  // --- Focus trap + auto-focus + focus restoration ---
  useEffect(() => {
    if (!open) return;

    const dialogContent = contentRef.current;
    if (!dialogContent) return;

    // Remember what had focus before the dialog opened.
    previousFocusRef.current = document.activeElement as HTMLElement | null;

    // Auto-focus the preferred element (or the first focusable) inside the dialog.
    // Use requestAnimationFrame to ensure the DOM has painted.
    const rafId = requestAnimationFrame(() => {
      const preferred = dialogContent.querySelector('[data-autofocus]') as HTMLElement | null;
      if (preferred && typeof preferred.focus === 'function') {
        preferred.focus();
        // Only treat the preferred element as autofocused if it actually
        // received focus (it may be disabled, hidden, etc.).
        if (document.activeElement === preferred) {
          return;
        }
      }
      const focusable = getFocusableElements(dialogContent);
      if (focusable.length > 0) {
        focusable[0].focus();
      } else {
        // No focusable elements — focus the container itself for screen readers.
        dialogContent.focus();
      }
    });

    // Trap Tab / Shift+Tab within the dialog.
    function handleTabTrap(event: KeyboardEvent) {
      if (event.key !== 'Tab') return;

      const focusable = getFocusableElements(dialogContent!);
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey) {
        // Shift+Tab: wrap from first to last.
        if (document.activeElement === first) {
          event.preventDefault();
          last.focus();
        }
      } else {
        // Tab: wrap from last to first.
        if (document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener('keydown', handleTabTrap);

    return () => {
      cancelAnimationFrame(rafId);
      document.removeEventListener('keydown', handleTabTrap);

      // Restore focus to the element that had it before the dialog opened.
      const previousFocus = previousFocusRef.current;
      if (previousFocus && typeof previousFocus.focus === 'function') {
        previousFocus.focus();
      }
    };
  }, [open, contentRef]);
}
