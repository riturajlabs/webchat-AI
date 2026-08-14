'use client';

import { useId, useState } from 'react';
import { FlaskConical, Globe, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

import { LOOPBACK_HOSTS, MAX_ALLOWED_DOMAINS, normalizeDomain } from '../domain';

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

  const preview = normalizeDomain(value);
  const typing = value.trim().length > 0;
  const missingLoopback = LOOPBACK_HOSTS.filter((host) => !domains.includes(host));

  function add() {
    const entry = value.trim();
    if (!entry) {
      setError('Enter a domain to add.');
      return;
    }
    const normalized = normalizeDomain(entry);
    if (normalized === null) {
      setError('Enter a hostname like example.com, a *.example.com wildcard, or an http(s) URL.');
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

  function addLoopbackHosts() {
    if (missingLoopback.length === 0) {
      return;
    }
    onChange([...domains, ...missingLoopback]);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <Label htmlFor={inputId}>Allowed domains</Label>
        <span className="text-xs text-muted-foreground">
          {domains.length}/{MAX_ALLOWED_DOMAINS}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        Only these domains may embed the widget. Enter a full URL — only its hostname is saved — or
        use *.example.com to allow every subdomain. An empty list blocks embeds until you add a
        domain.
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
      {typing ? (
        <p
          role="status"
          className={cn(
            'rounded-md px-3 py-2 text-sm',
            preview !== null ? 'bg-primary/5 text-primary' : 'bg-destructive/10 text-destructive',
          )}
        >
          {preview !== null ? (
            <>
              Will be saved as: <span className="font-mono">{preview}</span>
            </>
          ) : (
            'Not a valid domain. Use example.com, *.example.com, or an http(s) URL.'
          )}
        </p>
      ) : null}
      {error !== null ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {domains.length === 0 ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          No allowed domains — the widget is blocked from embedding on any website until you add a
          domain.
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
      <div className="flex flex-col gap-2 rounded-md border border-dashed p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <Label>Development domains</Label>
            <p className="text-sm text-muted-foreground">
              localhost and 127.0.0.1 are auto-permitted while the API runs in development, so you
              can test the embed locally without touching the list.
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addLoopbackHosts}
            disabled={missingLoopback.length === 0}
          >
            <FlaskConical aria-hidden="true" />
            Add localhost testing
          </Button>
        </div>
        {missingLoopback.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {LOOPBACK_HOSTS.join(' and ')} are already in the allowlist.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            Adds {missingLoopback.join(' and ')} — recommended if you test on a domain other than
            localhost (e.g. 10.0.0.1 or a staging host).
          </p>
        )}
      </div>
    </div>
  );
}
