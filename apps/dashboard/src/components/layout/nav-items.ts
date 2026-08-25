import type { LucideIcon } from 'lucide-react';
import {
  BarChart3,
  BookOpen,
  Bot,
  CircleUser,
  CreditCard,
  FlaskConical,
  KeyRound,
  LayoutDashboard,
  LibraryBig,
  MessagesSquare,
  Puzzle,
  Receipt,
  Rocket,
  Settings,
  ShieldCheck,
} from 'lucide-react';

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown only to platform super admins (Phase 15, `/api/admin` is super_admin-only). */
  adminOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/websites', label: 'Websites', icon: Bot },
  { href: '/knowledge', label: 'Knowledge Base', icon: LibraryBig },
  { href: '/conversations', label: 'Conversations', icon: MessagesSquare },
  { href: '/analytics', label: 'Analytics', icon: BarChart3 },
  { href: '/usage', label: 'Usage', icon: CreditCard },
  { href: '/billing', label: 'Billing', icon: Receipt },
  { href: '/widget/setup', label: 'Setup Assistant', icon: Rocket },
  { href: '/widget', label: 'Widget', icon: Puzzle },
  { href: '/widget-test', label: 'Widget Test', icon: FlaskConical },
  { href: '/api-keys', label: 'API Keys', icon: KeyRound },
  { href: '/docs', label: 'Documentation', icon: BookOpen },
  { href: '/profile', label: 'Profile', icon: CircleUser },
  { href: '/settings', label: 'Settings', icon: Settings },
  { href: '/admin', label: 'Admin', icon: ShieldCheck, adminOnly: true },
];

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Sidebar sections shared by the desktop rail and the mobile drawer. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Workspace',
    items: [NAV_ITEMS[0], NAV_ITEMS[1], NAV_ITEMS[2], NAV_ITEMS[3], NAV_ITEMS[4]],
  },
  {
    label: 'Assistant',
    items: [NAV_ITEMS[7], NAV_ITEMS[8], NAV_ITEMS[9]],
  },
  {
    label: 'Account',
    items: [NAV_ITEMS[5], NAV_ITEMS[6], NAV_ITEMS[10], NAV_ITEMS[11], NAV_ITEMS[12], NAV_ITEMS[13]],
  },
  {
    label: 'Platform',
    items: [NAV_ITEMS[14]],
  },
];

/** Nav items visible to the authenticated principal's role (Phase 15). */
export function visibleNavGroups(role: string | undefined): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.adminOnly || role === 'super_admin'),
  })).filter((group) => group.items.length > 0);
}

/**
 * Active-state matching for section navs: exact route or a nested child
 * (`/conversations/abc` keeps "Conversations" highlighted) without
 * prefix collisions (`/widget-test` never activates `/widget`).
 */
export function isNavActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
