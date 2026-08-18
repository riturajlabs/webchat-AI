'use client';

import { useRef } from 'react';
import { X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useAccessibleDialog } from '@/hooks/use-accessible-dialog';

/**
 * Accessible confirmation dialog for admin mutations (suspend/activate,
 * user suspend, force logout). Mirrors the existing dialog pattern used by
 * the websites feature (no shadcn dialog primitive in this repo).
 *
 * Keyboard behavior (WCAG 2.1):
 * - Escape closes the dialog.
 * - Tab / Shift+Tab cycles within the dialog.
 * - Focus returns to the trigger element on close.
 * - Background content is marked inert while open.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  onConfirm,
  title,
  description,
  confirmLabel,
  cancelLabel = 'Cancel',
  isPending = false,
  variant = 'default',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  isPending?: boolean;
  variant?: 'default' | 'destructive';
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  const close = () => onOpenChange(false);

  useAccessibleDialog({
    open,
    onClose: close,
    contentRef,
  });

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
    >
      <div
        className="absolute inset-0 bg-black/50"
        data-dialog-overlay
        onClick={close}
        aria-hidden="true"
      />
      <div
        ref={contentRef}
        className="relative z-10 w-full max-w-md rounded-lg border bg-background p-6 shadow-lg"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="confirm-dialog-title" className="font-sans text-lg font-semibold">
              {title}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </div>
          <Button variant="ghost" size="icon" onClick={close} aria-label="Close dialog">
            <X aria-hidden="true" />
          </Button>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={close} disabled={isPending}>
            {cancelLabel}
          </Button>
          <Button
            variant={variant}
            onClick={() => void onConfirm()}
            disabled={isPending}
            data-testid="confirm-dialog-confirm"
          >
            {isPending ? 'Working…' : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
