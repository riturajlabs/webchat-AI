'use client';

import { KeyRound } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * API keys are read-only in this phase: the backend has no API-key management
 * endpoint yet (docs/06 Phase 7). We render a production-grade empty state
 * instead of inventing mock data.
 */
export function ApiKeysPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">API Keys</h1>
        <p className="text-sm text-muted-foreground">
          Manage programmatic access to your assistants.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>API key management</CardTitle>
          <CardDescription>Create and revoke access keys.</CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={KeyRound}
            title="API keys are not available yet"
            description="API key management will appear once the API key API is available."
          />
        </CardContent>
      </Card>
    </div>
  );
}
