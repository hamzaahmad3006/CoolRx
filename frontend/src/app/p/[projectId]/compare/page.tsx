import { BeforeAfterPage } from '@/features/BeforeAfter/BeforeAfterPage';

interface PageProps {
  readonly params: Promise<{ readonly projectId: string }>;
  readonly searchParams: Promise<{ readonly plan?: string }>;
}

/** Route entry only. UI in the feature module, logic in its hook. */
export default async function Page({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const { plan } = await searchParams;

  return (
    <BeforeAfterPage
      projectId={projectId}
      planId={plan ?? 'plan-fixture-01'}
      districtName="Phoenix · Encanto"
      districtContext="2025-07-15 15:00 · 80 m · 35 °C"
    />
  );
}
