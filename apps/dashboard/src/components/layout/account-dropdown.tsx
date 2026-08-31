'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Check,
  ChevronDown,
  ChevronRight,
  Home,
  LogOut,
  Monitor,
  Moon,
  Settings,
  Sun,
  User,
} from 'lucide-react';
import { useTheme } from 'next-themes';

import { Avatar } from '@/components/ui/avatar';
import { cn } from '@/lib/utils';

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
] as const;

type ThemeValue = (typeof THEME_OPTIONS)[number]['value'];

type UserLike = {
  name: string;
  email: string;
  /** Profile photo data-URL; null/absent → initials fallback. */
  avatar_url?: string | null;
};

type AccountDropdownProps = {
  user: UserLike | null;
  logout: () => void;
  isLoggingOut: boolean;
  setIsLoggingOut: React.Dispatch<React.SetStateAction<boolean>>;
};

function MenuItemLink({
  href,
  icon: Icon,
  children,
  onNavigate,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      role="menuitem"
      onClick={onNavigate}
      className="flex h-9 items-center gap-3 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      {children}
    </Link>
  );
}

export function AccountDropdown({
  user,
  logout,
  isLoggingOut,
  setIsLoggingOut,
}: AccountDropdownProps) {
  const [open, setOpen] = useState(false);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const { theme, setTheme } = useTheme();
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const activeTheme = (theme as ThemeValue | undefined) ?? 'system';

  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    setAppearanceOpen(false);
    if (restoreFocus) {
      triggerRef.current?.focus();
    }
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        close();
      }
    }
    function onPointerDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        close(false);
      }
    }
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousedown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('mousedown', onPointerDown);
    };
  }, [open, close]);

  const router = useRouter();

  async function handleSignOut() {
    if (isLoggingOut) {
      return;
    }
    setOpen(false);
    setIsLoggingOut(true);
    try {
      await logout();
      router.push('/');
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="account-menu"
        onClick={() => setOpen((v) => !v)}
        className="flex h-14 w-full items-center gap-2.5 rounded-lg px-2 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <Avatar name={user?.name} avatarUrl={user?.avatar_url} className="h-8 w-8 text-xs" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-foreground">
            {user?.name ?? ''}
          </span>
          <span className="block truncate text-xs text-muted-foreground">{user?.email ?? ''}</span>
        </span>
        <ChevronDown
          className={cn(
            'size-4 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-180',
          )}
          aria-hidden="true"
        />
      </button>

      {open ? (
        <div
          id="account-menu"
          role="menu"
          aria-label="Account"
          className="absolute bottom-full right-0 z-50 mb-2 w-56 origin-bottom-right rounded-lg border border-border bg-popover p-1.5 text-popover-foreground shadow-lg"
        >
          <div className="flex items-center gap-3 border-b border-border px-2.5 py-2.5">
            <Avatar name={user?.name} avatarUrl={user?.avatar_url} className="h-8 w-8 text-xs" />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">{user?.name ?? ''}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {user?.email ?? ''}
              </span>
            </span>
          </div>

          <div className="flex flex-col gap-0.5 pt-1.5">
            <MenuItemLink href="/" icon={Home} onNavigate={() => close()}>
              Home
            </MenuItemLink>
            <MenuItemLink href="/profile" icon={User} onNavigate={() => close()}>
              Profile
            </MenuItemLink>
            <MenuItemLink href="/settings" icon={Settings} onNavigate={() => close()}>
              Settings
            </MenuItemLink>
          </div>

          <div className="my-1.5 h-px bg-border" />

          <div className="relative">
            <button
              type="button"
              role="menuitem"
              aria-haspopup="menu"
              aria-expanded={appearanceOpen}
              onClick={() => setAppearanceOpen((v) => !v)}
              className="flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <span
                className="relative flex size-4 shrink-0 items-center justify-center"
                aria-hidden="true"
              >
                <Sun className="absolute size-4 dark:hidden" aria-hidden="true" />
                <Moon className="absolute hidden size-4 dark:block" aria-hidden="true" />
              </span>
              Appearance
              <ChevronRight
                className={cn(
                  'ml-auto size-4 shrink-0 text-muted-foreground transition-transform',
                  appearanceOpen && 'rotate-90',
                )}
                aria-hidden="true"
              />
            </button>

            {appearanceOpen ? (
              <div
                role="menu"
                aria-label="Appearance"
                className="absolute left-full top-0 z-50 ml-1 w-36 rounded-lg border border-border bg-popover p-1 shadow-lg"
              >
                {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
                  <button
                    key={value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={activeTheme === value}
                    onClick={() => {
                      setTheme(value);
                      close();
                    }}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                      activeTheme === value
                        ? 'font-medium text-foreground'
                        : 'text-muted-foreground',
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden="true" />
                    {label}
                    {activeTheme === value ? (
                      <Check className="ml-auto size-3.5" aria-hidden="true" />
                    ) : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div className="my-1.5 h-px bg-border" />

          <button
            type="button"
            role="menuitem"
            onClick={handleSignOut}
            disabled={isLoggingOut}
            className="flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
          >
            <LogOut className="size-4 shrink-0" aria-hidden="true" />
            {isLoggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      ) : null}
    </div>
  );
}
