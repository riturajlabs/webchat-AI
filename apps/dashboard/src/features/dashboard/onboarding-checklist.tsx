'use client';

import Link from 'next/link';
import { Circle, CircleCheckBig } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export interface OnboardingStep {
  label: string;
  href: string;
  done: boolean;
}

const DEFAULT_STEPS: OnboardingStep[] = [
  { label: 'Add website', href: '/websites', done: false },
  { label: 'Crawl knowledge', href: '/knowledge', done: false },
  { label: 'Install widget', href: '/widget', done: false },
];

export function OnboardingChecklist({ steps }: { steps?: OnboardingStep[] }) {
  const items = steps ?? DEFAULT_STEPS;
  const completed = items.filter((s) => s.done).length;
  const percent = Math.round((completed / items.length) * 100);
  const nextIndex = items.findIndex((s) => !s.done);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <div>
          <CardTitle>Getting started</CardTitle>
          <CardDescription>
            {completed === items.length
              ? 'All set — your assistant is live.'
              : `${completed} of ${items.length} steps complete`}
          </CardDescription>
        </div>
        <span className="text-sm font-medium text-muted-foreground">{percent}%</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={`${completed} of ${items.length} setup steps complete`}
          aria-label="Setup progress"
          className="h-2 w-full overflow-hidden rounded-full bg-muted"
        >
          <div
            className="h-full rounded-full bg-blue-600 transition-all"
            style={{ width: `${percent}%` }}
          />
        </div>
        <ol aria-label="Setup steps" className="flex flex-col divide-y">
          {items.map(({ label, href, done }, index) => {
            const isNext = index === nextIndex;
            return (
              <li key={label} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex min-w-0 items-center gap-2.5 text-sm">
                  {done ? (
                    <CircleCheckBig
                      className="size-4 shrink-0 text-blue-600 dark:text-blue-400"
                      aria-hidden="true"
                    />
                  ) : (
                    <Circle className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  )}
                  <span className={done ? 'text-muted-foreground line-through' : 'font-medium'}>
                    {label}
                  </span>
                  {isNext ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
                      Up next
                    </span>
                  ) : null}
                </span>
                {!done ? (
                  <Button
                    asChild
                    variant="ghost"
                    size="sm"
                    className="shrink-0 text-blue-600 dark:text-blue-400"
                  >
                    <Link href={href}>
                      Open
                      <span className="sr-only">{label}</span>
                    </Link>
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
