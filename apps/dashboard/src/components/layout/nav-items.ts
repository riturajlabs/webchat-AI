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
  /** Shown only to platform admins (`role=admin`, ADR-006 §Admin UI). */
  adminOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/websites', label: 'Websites', icon: Bot },
  { href: '/knowledge', label: 'Knowledge Base', icon: LibraryBig },
  { href: '/conversations', label: 'Conversations', icon: MessagesSquare },
  { href: '/analytics', label: 'Analytics', icon: BarChart3 },
  { href: '/usage', label: 'Usage', icon: CreditCard },
  { href: '/billing', label: 'Billing', icon: Receipt },
  { href: '/widget', label: 'Widget', icon: Puzzle },
  { href: '/widget-test', label: 'Widget Test', icon: FlaskConical },
  { href: '/api-keys', label: 'API Keys', icon: KeyRound },
  { href: '/docs', label: 'Documentation', icon: BookOpen },
  { href: '/profile', label: 'Profile', icon: CircleUser },
  { href: '/settings', label: 'Settings', icon: Settings },
  { href: '/admin', label: 'Admin', icon: ShieldCheck, adminOnly: true },
];

/** Nav items visible to the authenticated principal's role (ADR-006 §Admin UI). */
export function visibleNavItems(role: string | undefined): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.adminOnly || role === 'admin');
}
