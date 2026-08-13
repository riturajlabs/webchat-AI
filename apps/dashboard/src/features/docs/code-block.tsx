'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

import { Button } from '@/components/ui/button';

/**
 * Static code snippet with a copy button (developer docs). Keeps the copy
 * state local so each snippet shows its own success feedback.
 */
export function CodeBlock({
  code,
  language = 'html',
  copyLabel = 'Copy code',
}: {
  code: string;
  language?: string;
  copyLabel?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="overflow-hidden rounded-md border border-input bg-muted">
      <div className="flex items-center justify-between gap-2 border-b border-input bg-muted/60 px-3 py-1.5">
        <span className="text-xs font-medium text-muted-foreground">{language}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-xs"
          aria-label={copied ? 'Copied!' : copyLabel}
          onClick={() => void copy()}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? 'Copied!' : 'Copy'}
        </Button>
      </div>
      <pre className="max-h-80 overflow-auto p-4 font-mono text-xs leading-relaxed">{code}</pre>
    </div>
  );
}
