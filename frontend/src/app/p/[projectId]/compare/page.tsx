import { BeforeAfterPage } from '@/features/BeforeAfter/BeforeAfterPage';

interface PageProps {
  readonly params: Promise<{ readonly projectId: string }>;
  readonly searchParams: Promise<{ readonly plan?: string }>;
}

/**
 * Route entry only. UI in the feature module, logic in its hook.
 *
 * `plan` may be absent, and the page then falls back to the plan in session —
 * the one the Prescribe step just produced. It used to fall back to
 * `plan-fixture-01`, so arriving here without the query parameter asked the API
 * for a fixture id it had never issued and the page rendered its error state
 * over a plan that existed perfectly well.
 */
export default async function Page({ params, searchParams }: PageProps) {
  const { projectId } = await params;
  const { plan } = await searchParams;

  return <BeforeAfterPage projectId={projectId} planId={plan ?? null} />;
}
