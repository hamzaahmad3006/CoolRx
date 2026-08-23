import { DiagnosisPage } from '@/features/Diagnosis/DiagnosisPage';

interface PageProps {
  readonly params: Promise<{ readonly projectId: string }>;
}

/** Route entry only. UI in the feature module, logic in its hook. */
export default async function Page({ params }: PageProps) {
  const { projectId } = await params;

  return (
    <DiagnosisPage
      projectId={projectId}
    />
  );
}
