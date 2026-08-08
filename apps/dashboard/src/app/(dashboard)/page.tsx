import { Button } from '@/components/ui/button';

export default function DashboardHome() {
  return (
    <div className="flex flex-col items-center justify-center gap-6 text-center">
      <h1 className="font-sans text-4xl font-bold tracking-tight">WebChat AI</h1>
      <p className="max-w-md font-mono text-sm text-muted-foreground">
        Website-specific AI assistants, built from your content with RAG.
      </p>
      <p className="font-mono text-xs text-muted-foreground/70">Phase 1 · Project Foundation</p>
      <Button asChild>
        <a href="/websites">Create your first assistant</a>
      </Button>
    </div>
  );
}
