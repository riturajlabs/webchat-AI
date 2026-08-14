import type { Metadata } from 'next';

import { WidgetTestPage as WidgetTestFeature } from '@/features/widget/widget-test-page';

export const metadata: Metadata = {
  title: 'Widget Test',
};

export default function WidgetTestPage() {
  return <WidgetTestFeature />;
}
