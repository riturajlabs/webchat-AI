import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Merge Tailwind class strings, resolving conflicts in favor of the last value. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
