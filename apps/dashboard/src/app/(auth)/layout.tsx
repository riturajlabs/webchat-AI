import { Bot } from 'lucide-react';

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Bot className="size-5" aria-hidden="true" />
          </span>
          <p className="font-semibold">WebChat AI</p>
        </div>
        <div className="rounded-lg border bg-background p-6 shadow-sm">{children}</div>
      </div>
    </div>
  );
}
