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

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Widget Test is a developer tool and must never ship in the production nav. */
const SHOW_WIDGET_TEST = process.env.NODE_ENV !== 'production';

/**
 * Sidebar/mobile information architecture (audit Phase F). Order within each
 * group mirrors the previous flat list.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Overview',
    items: [{ href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard }],
  },
  {
    label: 'Product',
    items: [
      { href: '/websites', label: 'Websites', icon: Bot },
      { href: '/knowledge', label: 'Knowledge Base', icon: LibraryBig },
      { href: '/conversations', label: 'Conversations', icon: MessagesSquare },
      { href: '/widget', label: 'Widget', icon: Puzzle },
    ],
  },
  {
    label: 'Analytics',
    items: [
      { href: '/analytics', label: 'Analytics', icon: BarChart3 },
      { href: '/usage', label: 'Usage', icon: CreditCard },
    ],
  },
  {
    label: 'Developer',
    items: [
      ...(SHOW_WIDGET_TEST
        ? [{ href: '/widget-test', label: 'Widget Test', icon: FlaskConical }]
        : []),
      { href: '/api-keys', label: 'API Keys', icon: KeyRound },
      { href: '/docs', label: 'Documentation', icon: BookOpen },
    ],
  },
  {
    label: 'Account',
    items: [
      { href: '/billing', label: 'Billing', icon: Receipt },
      { href: '/profile', label: 'Profile', icon: CircleUser },
      { href: '/settings', label: 'Settings', icon: Settings },
    ],
  },
  {
    label: 'Admin',
    items: [{ href: '/admin', label: 'Admin', icon: ShieldCheck, adminOnly: true }],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

/** All nav items visible to the authenticated principal's role (Phase 15). */
export function visibleNavItems(role: string | undefined): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.adminOnly || role === 'super_admin');
}

/** Nav groups visible to the role; empty groups are dropped (audit Phase F). */
export function visibleNavGroups(role: string | undefined): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.adminOnly || role === 'super_admin'),
  })).filter((group) => group.items.length > 0);
}
