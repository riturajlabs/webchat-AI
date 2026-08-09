import type { Metadata } from 'next';

import { WidgetPage as WidgetFeature } from '@/features/widget/widget-page';

export const metadata: Metadata = {
  title: 'Widget',
};

export default function WidgetPage() {
  return <WidgetFeature />;
}
