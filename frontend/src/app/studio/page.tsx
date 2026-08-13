import type { Metadata } from 'next';

import { AoiStudioPage } from '@/features/AoiStudio/AoiStudioPage';

export const metadata: Metadata = {
  // The root layout appends "· CoolRx" via its title template, so this must not.
  title: 'Set up an analysis',
  description:
    'Place a compliant area of interest and choose the measurement window before '
    + 'running a heat diagnosis.',
};

export default function Page() {
  return <AoiStudioPage />;
}
