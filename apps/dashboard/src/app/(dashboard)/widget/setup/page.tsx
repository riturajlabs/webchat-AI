import type { Metadata } from 'next';

import { WidgetSetupWizard } from '@/features/widget/widget-setup-wizard';

export const metadata: Metadata = {
  title: 'Widget Setup',
};

export default function WidgetSetupPage() {
  return <WidgetSetupWizard />;
}
