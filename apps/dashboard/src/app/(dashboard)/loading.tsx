import { PageSkeleton } from '@/components/ui/page-skeleton';

export default function DashboardLoading() {
  return (
    <div className="flex-1 px-4 py-8 md:px-10">
      <PageSkeleton />
    </div>
  );
}
