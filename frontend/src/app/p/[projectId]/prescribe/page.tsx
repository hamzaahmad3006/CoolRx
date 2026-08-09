import { PrescriptionPage } from '@/features/Prescription/PrescriptionPage';

interface PageProps {
  readonly params: Promise<{ readonly projectId: string }>;
}

/**
 * Route entry only. UI lives in the feature module, logic in its hook.
 */
export default async function Page({ params }: PageProps) {
  const { projectId } = await params;

  return (
    <PrescriptionPage
      projectId={projectId}
      districtName="Phoenix · Encanto"
      districtContext="2025-07-15 15:00 · 80 m · 35 °C"
    />
  );
}
