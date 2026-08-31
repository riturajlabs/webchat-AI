'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, Check, Loader2, Monitor, Moon, Sun, X } from 'lucide-react';
import { useTheme } from 'next-themes';

import { api } from '@/lib/api';
import { clearSession } from '@/lib/session';
import { useAuth } from '@/features/auth/auth-context';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { useAccessibleDialog } from '@/hooks/use-accessible-dialog';
import { cn } from '@/lib/utils';

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
] as const;

type ThemeValue = (typeof THEME_OPTIONS)[number]['value'];

function AppearanceCard() {
  const { theme, setTheme } = useTheme();
  const active = (theme as ThemeValue | undefined) ?? 'system';

  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>Choose how the dashboard looks for you.</CardDescription>
      </CardHeader>
      <CardContent>
        <div role="radiogroup" aria-label="Theme" className="flex flex-wrap gap-2">
          {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={active === value}
              onClick={() => setTheme(value)}
              className={cn(
                'inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm transition-colors',
                'hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                active === value
                  ? 'border-primary/60 text-foreground'
                  : 'border-border text-muted-foreground',
              )}
            >
              <Icon className="size-4" aria-hidden="true" />
              {label}
              {active === value ? (
                <Check className="size-3.5 text-primary" aria-hidden="true" />
              ) : null}
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function DeleteAccountDialog({
  open,
  onOpenChange,
  email,
  onConfirm,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  email: string;
  onConfirm: () => void;
  isPending: boolean;
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [confirmation, setConfirmation] = useState('');
  const close = () => onOpenChange(false);

  useAccessibleDialog({ open, onClose: close, contentRef });

  const matches = confirmation.trim() === email;

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-account-dialog-title"
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
          <div className="flex gap-3">
            <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-destructive/10 text-destructive">
              <AlertTriangle className="size-5" aria-hidden="true" />
            </span>
            <div>
              <h2 id="delete-account-dialog-title" className="font-sans text-lg font-semibold">
                Delete account
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                This permanently deletes your account, your workspace and all of its data (websites,
                documents, conversations, API keys and more). This action cannot be undone.
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={close}
            disabled={isPending}
            aria-label="Close dialog"
          >
            <X aria-hidden="true" />
          </Button>
        </div>

        <div className="mb-5 space-y-1.5">
          <Label htmlFor="delete-account-confirm">
            Type <span className="font-semibold">{email}</span> to confirm
          </Label>
          <Input
            id="delete-account-confirm"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder={email}
            autoComplete="off"
            disabled={isPending}
          />
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={close} disabled={isPending}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => void onConfirm()}
            disabled={!matches || isPending}
            data-testid="delete-account-confirm"
          >
            {isPending ? (
              <>
                <Loader2 className="animate-spin" aria-hidden="true" />
                Deleting…
              </>
            ) : (
              'Delete my account'
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

function DangerZone() {
  const { user } = useAuth();
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const email = user?.email ?? '';

  async function confirmDelete() {
    if (isPending) {
      return;
    }
    setIsPending(true);
    try {
      await api.delete('/api/auth/me');
      clearSession();
      router.push('/login');
    } catch (error) {
      setIsPending(false);
      setError(error instanceof Error ? error.message : 'Failed to delete your account.');
    }
  }

  return (
    <Card className="border-destructive/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="size-4" aria-hidden="true" />
          Danger zone
        </CardTitle>
        <CardDescription>
          Deleting your account is permanent and removes your workspace and all of its data.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Button
          variant="destructive"
          className="w-fit"
          onClick={() => {
            setError(null);
            setDialogOpen(true);
          }}
        >
          Delete account
        </Button>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>

      <DeleteAccountDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open && !isPending) {
            setDialogOpen(false);
          }
        }}
        email={email}
        onConfirm={() => void confirmDelete()}
        isPending={isPending}
      />
    </Card>
  );
}

export function SettingsPage() {
  const { user, status } = useAuth();

  if (status === 'loading' || !user) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title="Settings"
          description="Configure your account and workspace preferences."
        />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Configure your account and workspace preferences."
      />
      <AppearanceCard />
      <DangerZone />
    </div>
  );
}
