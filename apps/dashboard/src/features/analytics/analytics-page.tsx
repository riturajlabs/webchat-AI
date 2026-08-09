'use client';

import { BarChart3 } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * Analytics is read-only in this phase: the backend has no analytics API yet
 * (docs/06 Phase 7). We render a production-grade empty state instead of
 * inventing mock data.
 */
export function AnalyticsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Chat, visitor, and knowledge-base usage statistics.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Usage analytics</CardTitle>
          <CardDescription>Daily chats, visitors, and response times.</CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={BarChart3}
            title="Analytics are not available yet"
            description="Usage statistics will appear once the analytics API is available."
          />
        </CardContent>
      </Card>
    </div>
  );
}
