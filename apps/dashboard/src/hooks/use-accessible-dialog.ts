'use client';

import { useCallback, useEffect, useRef } from 'react';

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
  /** Selector for the overlay/backdrop element. Default: '[data-dialog-overlay]'. */
  overlaySelector?: string;
}

/**
 * Implements WCAG 2.1 modal dialog behavior:
 *
 * - **Focus trapping**: Tab/Shift+Tab cycles within the dialog.
 * - **Escape key**: Calls `onClose`.
 * - **Focus restoration**: Returns focus to the element that had it before the dialog opened.
 * - **Auto-focus**: Moves focus to the first focusable element inside the dialog.
 * - **Background isolation**: Sets `inert` on sibling elements so background content
 *   cannot receive keyboard focus or be targeted by assistive technology.
 *
 * All behavior is implemented with native DOM APIs — no extra dependencies.
 */
export function useAccessibleDialog({
  open,
  onClose,
  contentRef,
  overlaySelector = '[data-dialog-overlay]',
}: UseAccessibleDialogOptions) {
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

  // --- Focus trap + auto-focus + inert background ---
  useEffect(() => {
    if (!open) return;

    const dialogContent = contentRef.current;
    if (!dialogContent) return;

    // Remember what had focus before the dialog opened.
    previousFocusRef.current = document.activeElement as HTMLElement | null;

    // Mark background siblings as inert so they cannot receive focus.
    const inertSiblings: HTMLElement[] = [];
    const parent = dialogContent.parentElement;
    if (parent) {
      for (const sibling of Array.from(parent.children)) {
        if (sibling !== dialogContent && !sibling.hasAttribute('inert')) {
          sibling.setAttribute('inert', '');
          inertSiblings.push(sibling as HTMLElement);
        }
      }
    }

    // Auto-focus the first focusable element inside the dialog.
    // Use requestAnimationFrame to ensure the DOM has painted.
    const rafId = requestAnimationFrame(() => {
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

      // Remove inert from siblings.
      for (const sibling of inertSiblings) {
        sibling.removeAttribute('inert');
      }

      // Restore focus to the element that had it before the dialog opened.
      const previousFocus = previousFocusRef.current;
      if (previousFocus && typeof previousFocus.focus === 'function') {
        previousFocus.focus();
      }
    };
  }, [open, contentRef]);

  // --- Overlay click handler (returned for consumer use) ---
  const handleOverlayClick = useCallback(
    (event: React.MouseEvent) => {
      // Only close if the click is directly on the overlay, not on child elements.
      const overlay = contentRef.current?.parentElement?.querySelector(overlaySelector);
      if (event.target === overlay) {
        onClose();
      }
    },
    [onClose, contentRef, overlaySelector],
  );

  return { handleOverlayClick };
}
