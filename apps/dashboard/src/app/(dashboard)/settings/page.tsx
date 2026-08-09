import type { Metadata } from 'next';

import { SettingsPage } from '@/features/settings/settings-page';

export const metadata: Metadata = {
  title: 'Settings',
};

export default function SettingsPageRoute() {
  return <SettingsPage />;
}
