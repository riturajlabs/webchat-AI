'use client';

import { useId, useState } from 'react';
import { Globe, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import { MAX_ALLOWED_DOMAINS, normalizeDomain } from '../domain';

export function AllowedDomainsEditor({
  domains,
  onChange,
}: {
  domains: string[];
  onChange: (domains: string[]) => void;
}) {
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();

  function add() {
    const entry = value.trim();
    if (!entry) {
      setError('Enter a domain to add.');
      return;
    }
    const normalized = normalizeDomain(entry);
    if (normalized === null) {
      setError('Use a bare hostname like example.com (optionally *.example.com).');
      return;
    }
    if (domains.includes(normalized)) {
      setError(`${normalized} is already in the list.`);
      return;
    }
    if (domains.length >= MAX_ALLOWED_DOMAINS) {
      setError(`No more than ${MAX_ALLOWED_DOMAINS} domains are allowed.`);
      return;
    }
    onChange([...domains, normalized]);
    setValue('');
    setError(null);
  }

  function remove(domain: string) {
    onChange(domains.filter((entry) => entry !== domain));
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <Label htmlFor={inputId}>Allowed domains</Label>
        <span className="text-xs text-muted-foreground">
          {domains.length}/{MAX_ALLOWED_DOMAINS}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        Only these domains may embed the widget. Leave empty to allow any origin, or use
        *.example.com to allow every subdomain.
      </p>
      <div className="flex items-center gap-2">
        <Input
          id={inputId}
          value={value}
          placeholder="example.com"
          aria-invalid={error !== null}
          onChange={(event) => {
            setValue(event.target.value);
            setError(null);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add}>
          <Plus aria-hidden="true" />
          Add
        </Button>
      </div>
      {error !== null ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {domains.length === 0 ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          No allowed domains — any website can embed this widget.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {domains.map((domain) => (
            <li
              key={domain}
              className="flex items-center justify-between gap-2 rounded-md border border-input px-3 py-2"
            >
              <span className="flex items-center gap-2 font-mono text-sm">
                <Globe aria-hidden="true" className="size-4 text-muted-foreground" />
                {domain}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${domain}`}
                onClick={() => remove(domain)}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
