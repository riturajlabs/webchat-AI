'use client';

import { MessagesSquare } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';

/**
 * Conversations is read-only in this phase: the backend has no conversation
 * management API yet (docs/06 Phase 7). We render a production-grade empty
 * state instead of inventing mock data.
 */
export function ConversationsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-bold tracking-tight">Conversations</h1>
        <p className="text-sm text-muted-foreground">
          Chat history and per-assistant conversation threads.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Conversation history</CardTitle>
          <CardDescription>Your visitors&apos; conversations will be listed here.</CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={MessagesSquare}
            title="Conversation management is not available yet"
            description="Conversation analytics will appear once the conversation management API is available."
          />
        </CardContent>
      </Card>
    </div>
  );
}
