import { Skeleton } from '@/components/ui/skeleton';

/** Loading state for the auth routes (login/signup/forgot/reset/verify). */
export default function AuthLoading() {
  return (
    <div className="flex flex-col gap-5" role="status" aria-label="Loading page">
      <Skeleton className="h-6 w-36" />
      <div className="flex flex-col gap-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
      <Skeleton className="h-4 w-44" />
    </div>
  );
}
