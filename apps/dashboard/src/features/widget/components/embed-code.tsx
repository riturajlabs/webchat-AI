'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';

import { buildInitExample, buildMountExample } from '../embed';

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="self-start"
      aria-label={copied ? 'Copied!' : label}
      onClick={() => void copy()}
    >
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      {copied ? 'Copied!' : 'Copy'}
    </Button>
  );
}

function CodeExample({
  label,
  code,
  copyLabel,
}: {
  label: string;
  code: string;
  copyLabel: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label>{label}</Label>
      <pre className="max-h-48 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
        {code}
      </pre>
      <CopyButton text={code} label={copyLabel} />
    </div>
  );
}

/**
 * Widget embed code (Phase 11.5). Renders the ready-to-paste script tag plus
 * the programmatic `init()`/`mount()` examples, each with a copy button that
 * gives inline success feedback. The widget id is baked into every snippet.
 */
export function EmbedCode({
  widgetId,
  embedScript,
}: {
  widgetId: string;
  /** Ready-to-paste script from the backend (authoritative script src). */
  embedScript: string;
}) {
  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">Widget embed code</CardTitle>
        <CardDescription className="text-sm">
          Paste this script on your site to activate the widget.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 p-4 pt-2">
        <CodeExample
          label="Basic usage — script tag"
          code={embedScript}
          copyLabel="Copy embed script"
        />

        <div className="border-t pt-4">
          <p className="mb-3 text-sm text-muted-foreground">
            For framework apps, import the SDK and call{' '}
            <code className="font-mono text-xs">init()</code> or{' '}
            <code className="font-mono text-xs">mount()</code> instead.
          </p>
          <div className="flex flex-col gap-4">
            <CodeExample
              label="Advanced usage — init()"
              code={buildInitExample(widgetId)}
              copyLabel="Copy init() example"
            />
            <CodeExample
              label="Advanced usage — mount()"
              code={buildMountExample(widgetId)}
              copyLabel="Copy mount() example"
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
