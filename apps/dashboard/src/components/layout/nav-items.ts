import type { LucideIcon } from 'lucide-react';
import {
  BarChart3,
  Bot,
  CircleUser,
  KeyRound,
  LayoutDashboard,
  LibraryBig,
  MessagesSquare,
  Puzzle,
  Settings,
} from 'lucide-react';

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/websites', label: 'Websites', icon: Bot },
  { href: '/knowledge', label: 'Knowledge Base', icon: LibraryBig },
  { href: '/conversations', label: 'Conversations', icon: MessagesSquare },
  { href: '/analytics', label: 'Analytics', icon: BarChart3 },
  { href: '/widget', label: 'Widget', icon: Puzzle },
  { href: '/api-keys', label: 'API Keys', icon: KeyRound },
  { href: '/profile', label: 'Profile', icon: CircleUser },
  { href: '/settings', label: 'Settings', icon: Settings },
];
