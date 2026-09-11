import Image from 'next/image';

import { cn } from '@/lib/utils';

/**
 * WebChat AI logo mark (canonical asset: `public/logo.png`).
 *
 * The asset is the logo mark only — it contains no wordmark/text, so callers
 * that render the brand lockup must keep the "WebChat AI" text separately.
 * The mark is transparent-backed and works on light and dark surfaces; it
 * inherits no background treatment so existing container styling (padding,
 * borders, rounded corners) stays untouched.
 *
 * Marks are square, so callers control the rendered size through `className`
 * (for example `h-8 w-8`) and the aspect ratio is preserved automatically.
 */
export function LogoMark({ className, alt = '' }: { className?: string; alt?: string }) {
  return (
    <Image
      src="/logo.png"
      alt={alt}
      width={500}
      height={500}
      sizes="4rem"
      className={cn('h-8 w-8 shrink-0 object-contain', className)}
    />
  );
}
