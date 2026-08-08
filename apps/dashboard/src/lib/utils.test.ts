import { describe, expect, it } from 'vitest';

import { cn } from './utils';

describe('cn', () => {
  it('joins class names and trims empty values', () => {
    expect(cn('a', undefined, null, false, 'b')).toBe('a b');
  });

  it('merges conflicting Tailwind classes in favor of the last one', () => {
    expect(cn('px-2 px-4', 'text-sm text-lg')).toBe('px-4 text-lg');
  });
});
