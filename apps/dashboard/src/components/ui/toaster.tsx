'use client';

import { Toaster as SonnerToaster } from 'sonner';

export function Toaster() {
  return (
    <SonnerToaster
      richColors
      position="bottom-right"
      closeButton
      toastOptions={{ classNames: { toast: 'rounded-md border shadow-sm' } }}
    />
  );
}
