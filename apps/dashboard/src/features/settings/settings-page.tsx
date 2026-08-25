'use client';

import { Settings as SettingsIcon } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';

/**
 * Settings editing is read-only in this phase: the backend has no settings
 * update API yet (docs/06 Phase 7). We render a production-grade empty state
 * instead of inventing mock data.
 */
export function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Configure your account and workspace preferences."
      />

      <Card>
        <CardHeader>
          <CardTitle>Workspace settings</CardTitle>
          <CardDescription>Account and workspace preferences.</CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={SettingsIcon}
            title="Settings editing is not available yet"
            description="Workspace settings will appear once the settings API is available."
          />
        </CardContent>
      </Card>
    </div>
  );
}
