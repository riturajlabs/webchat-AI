import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SettingsPage } from '@/features/settings/settings-page';

/**
 * Phase 7: Settings has no backend API yet. It must render a production-grade
 * empty state with a proper page layout — never mock data. API Keys gained a
 * real implementation, so it is covered by
 * `features/api-keys/api-keys-page.test.tsx` instead. Analytics gained a real
 * implementation in Phase 11.3 and is covered by
 * `features/analytics/analytics-page.test.tsx`.
 */
describe('unsupported feature pages', () => {
  it('settings renders a layout and an empty state', () => {
    render(<SettingsPage />);
    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByText('Settings editing is not available yet')).toBeInTheDocument();
  });
});
