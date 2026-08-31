'use client';

import {
  CalendarDays,
  Camera,
  CircleUser,
  Loader2,
  Mail,
  Pencil,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { useRef, useState } from 'react';

import { api } from '@/lib/api';
import { useAuth } from '@/features/auth/auth-context';
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/ui/page-header';
import { StatusBadge } from '@/components/ui/status-badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

const MAX_AVATAR_FILE_BYTES = 5 * 1024 * 1024;
const AVATAR_OUTPUT_SIZE = 256;
const AVATAR_OUTPUT_TYPE = 'image/jpeg';
const AVATAR_OUTPUT_QUALITY = 0.9;

const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('Could not read the selected image.'));
    reader.readAsDataURL(file);
  });
}

function imageFromDataUrl(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('The selected file is not a valid image.'));
    image.src = url;
  });
}

/**
 * Downscale an uploaded image to a square avatar and return it as a compact
 * JPEG data-URL (kept well under the backend's inline avatar size limit so the
 * value is stored in the user document, not on a third-party host).
 */
async function processAvatar(file: File): Promise<string> {
  if (file.size > MAX_AVATAR_FILE_BYTES) {
    throw new Error('Image must be 5 MB or smaller.');
  }
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    throw new Error('Please choose a PNG, JPEG, WebP or GIF image.');
  }
  const source = await readFileAsDataUrl(file);
  const image = await imageFromDataUrl(source);

  const size = AVATAR_OUTPUT_SIZE;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) {
    throw new Error('Could not process the image.');
  }

  const side = Math.min(image.naturalWidth, image.naturalHeight);
  const sourceX = (image.naturalWidth - side) / 2;
  const sourceY = (image.naturalHeight - side) / 2;
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, size, size);
  context.drawImage(image, sourceX, sourceY, side, side, 0, 0, size, size);
  return canvas.toDataURL(AVATAR_OUTPUT_TYPE, AVATAR_OUTPUT_QUALITY);
}

function ProfileAvatar({
  name,
  avatarUrl,
  onOpenPicker,
}: {
  name: string;
  avatarUrl?: string | null;
  onOpenPicker: () => void;
}) {
  return (
    <div className="relative shrink-0">
      <Avatar
        name={name}
        avatarUrl={avatarUrl}
        className="size-24 text-3xl ring-2 ring-background"
      />
      <button
        type="button"
        aria-label="Change profile photo"
        title="Change profile photo"
        onClick={onOpenPicker}
        className="absolute -bottom-1 -right-1 flex size-9 items-center justify-center rounded-full border border-border bg-background text-foreground shadow-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
      >
        <Camera className="size-4" aria-hidden="true" />
      </button>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  return (
    <StatusBadge className="border border-border bg-muted text-muted-foreground">
      {role.charAt(0).toUpperCase() + role.slice(1)}
    </StatusBadge>
  );
}

function InfoItem({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <dt className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="size-4" aria-hidden="true" />
        {label}
      </dt>
      <dd className="text-sm font-medium text-foreground">{children}</dd>
    </div>
  );
}

function validateName(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return 'Name cannot be empty.';
  }
  if (trimmed.length < 2) {
    return 'Name must be at least 2 characters.';
  }
  return null;
}

export function ProfilePage() {
  const { user, status, updateUser } = useAuth();
  const [isEditing, setIsEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState('');
  const [avatarDraft, setAvatarDraft] = useState<string | null | undefined>(undefined);
  const [nameError, setNameError] = useState<string | null>(null);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const currentUser = user ?? null;
  const name = currentUser?.name ?? '';
  const avatarUrl = currentUser?.avatar_url ?? null;

  const startEditing = (nextAvatarDraft?: string | null) => {
    setNameDraft(name);
    setNameError(null);
    setAvatarError(null);
    const draft =
      nextAvatarDraft === undefined ? (currentUser?.avatar_url ?? null) : nextAvatarDraft;
    setAvatarDraft(draft);
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setIsEditing(false);
    setNameDraft('');
    setAvatarDraft(undefined);
    setNameError(null);
    setAvatarError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const openPicker = () => fileInputRef.current?.click();

  const handleAvatarFile = async (file: File | undefined) => {
    if (!file) {
      return;
    }
    setAvatarError(null);
    setNameError(null);
    try {
      const processed = await processAvatar(file);
      startEditing(processed);
    } catch (error) {
      setAvatarError(error instanceof Error ? error.message : 'Could not process the image.');
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const effectiveAvatar: string | null = avatarDraft === undefined ? avatarUrl : avatarDraft;

  const nameChanged = nameDraft.trim() !== name;
  const avatarChanged = effectiveAvatar !== avatarUrl;
  const hasChanges = nameChanged || avatarChanged;

  const handleSave = async () => {
    if (isSaving) {
      return;
    }
    const trimmedName = nameDraft.trim();
    const error = validateName(trimmedName);
    setNameError(error);
    if (error) {
      return;
    }
    setIsSaving(true);
    try {
      const body: { name?: string; avatar_url?: string | null } = {};
      if (nameChanged) {
        body.name = trimmedName;
      }
      if (avatarChanged) {
        body.avatar_url = effectiveAvatar;
      }
      const updated = await api.patch<{ name: string; avatar_url?: string | null }>(
        '/api/auth/me',
        body,
      );
      updateUser({ name: updated.name, avatar_url: updated.avatar_url ?? null });
      setIsEditing(false);
      setNameDraft('');
      setAvatarDraft(undefined);
      setNameError(null);
      setAvatarError(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err) {
      setNameError(err instanceof Error ? err.message : 'Could not save your profile.');
    } finally {
      setIsSaving(false);
    }
  };

  if (status === 'loading' || !currentUser) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Profile" description="Your account details." />
        <Card>
          <CardContent className="flex items-center gap-4 p-6">
            <Skeleton className="size-24 rounded-full" />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-56" />
            </div>
          </CardContent>
        </Card>
        <div className="grid gap-4">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Profile" description="Your account details." />

      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_IMAGE_TYPES.join(',')}
        aria-label="Choose profile photo"
        className="sr-only"
        onChange={(event) => void handleAvatarFile(event.target.files?.[0])}
      />

      <Card>
        <CardContent className="flex flex-col items-center gap-4 p-6 sm:flex-row sm:items-center sm:gap-5">
          <ProfileAvatar name={name} avatarUrl={effectiveAvatar} onOpenPicker={openPicker} />
          <div className="flex w-full min-w-0 flex-1 flex-col items-center gap-1 text-center sm:items-start sm:text-left">
            <h2 className="font-sans text-xl font-semibold tracking-tight">
              {isEditing && nameDraft.trim() ? nameDraft.trim() : name}
            </h2>
            <span className="text-sm text-muted-foreground">{currentUser.email}</span>
            <div className="mt-1">
              <RoleBadge role={currentUser.role} />
            </div>
          </div>
          {!isEditing ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => startEditing()}
              className="shrink-0"
            >
              <Pencil className="size-4" aria-hidden="true" />
              Edit profile
            </Button>
          ) : null}
        </CardContent>
      </Card>

      {isEditing ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Personal information</CardTitle>
            <CardDescription>Update the details shown on your profile.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="profile-name">Name</Label>
              <Input
                id="profile-name"
                value={nameDraft}
                maxLength={100}
                onChange={(event) => {
                  setNameDraft(event.target.value);
                  if (nameError) {
                    setNameError(null);
                  }
                }}
                aria-invalid={nameError ? true : undefined}
              />
              {nameError ? (
                <p role="alert" className="text-sm text-destructive">
                  {nameError}
                </p>
              ) : null}
            </div>

            {avatarError ? (
              <p role="alert" className="text-sm text-destructive">
                {avatarError}
              </p>
            ) : null}

            <div className="flex flex-col gap-1.5">
              <Label>Email</Label>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Mail className="size-4 shrink-0" aria-hidden="true" />
                {currentUser.email}
              </div>
              <p className="text-xs text-muted-foreground">
                Email is managed by your authentication account and cannot be changed here.
              </p>
            </div>

            {effectiveAvatar ? (
              <button
                type="button"
                onClick={() => setAvatarDraft(null)}
                className="flex w-fit items-center gap-2 text-sm text-destructive transition-colors hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <Trash2 className="size-4" aria-hidden="true" />
                Remove photo
              </button>
            ) : (
              <button
                type="button"
                onClick={openPicker}
                className="flex w-fit items-center gap-2 text-sm text-primary transition-colors hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <Camera className="size-4" aria-hidden="true" />
                Add photo
              </button>
            )}

            <div className="flex flex-wrap items-center gap-3 pt-1">
              <Button
                type="button"
                onClick={() => void handleSave()}
                disabled={!hasChanges || isSaving}
              >
                {isSaving ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <span>Save changes</span>
                )}
              </Button>
              <Button type="button" variant="outline" onClick={cancelEditing} disabled={isSaving}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Account information</CardTitle>
          <CardDescription>Details from your signed-in account.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-6 sm:grid-cols-2">
            <InfoItem icon={CircleUser} label="Name">
              {name}
            </InfoItem>
            <InfoItem icon={Mail} label="Email">
              <span className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 break-all">{currentUser.email}</span>
                {currentUser.email_verified ? (
                  <span className="inline-flex items-center gap-1 text-sm font-medium text-green-700 dark:text-green-400">
                    <ShieldCheck className="size-4" aria-hidden="true" />
                    Verified
                  </span>
                ) : (
                  <VerifyEmailButton email={currentUser.email} />
                )}
              </span>
            </InfoItem>
            <InfoItem icon={CircleUser} label="Role">
              <span className="capitalize">{currentUser.role}</span>
            </InfoItem>
            <InfoItem icon={CalendarDays} label="Member since">
              {formatDate(currentUser.created_at)}
            </InfoItem>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

function VerifyEmailButton({ email }: { email: string }) {
  const [isPending, setIsPending] = useState(false);
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(
    null,
  );

  async function sendVerification() {
    if (isPending) {
      return;
    }
    setIsPending(true);
    setFeedback(null);
    try {
      await api.post('/api/auth/resend-verification', { email });
      setFeedback({
        type: 'success',
        text: 'Verification email sent. Please check your inbox.',
      });
    } catch (error) {
      setFeedback({
        type: 'error',
        text: error instanceof Error ? error.message : 'Failed to send the verification email.',
      });
    } finally {
      setIsPending(false);
    }
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => void sendVerification()}
        disabled={isPending}
      >
        {isPending ? (
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        ) : (
          <Mail className="size-4" aria-hidden="true" />
        )}
        {isPending ? 'Sending…' : 'Verify email'}
      </Button>
      {feedback ? (
        <span
          role={feedback.type === 'error' ? 'alert' : 'status'}
          className={cn(
            'text-sm',
            feedback.type === 'success' ? 'text-green-700 dark:text-green-400' : 'text-destructive',
          )}
        >
          {feedback.text}
        </span>
      ) : null}
    </span>
  );
}
