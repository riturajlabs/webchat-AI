import { DashboardLayoutClient } from '@/features/auth/dashboard-layout-client';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <DashboardLayoutClient>{children}</DashboardLayoutClient>;
}
