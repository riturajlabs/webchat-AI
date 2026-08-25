import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * Shared status pill used across features. Callers pass the feature-specific
 * color classes via `className` so each domain keeps its own status palette.
 */
export function StatusBadge({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        className,
      )}
      {...props}
    />
  );
}
