import type { Metadata } from 'next';

import { MethodsPage } from '@/features/Methods/MethodsPage';

export const metadata: Metadata = {
  title: 'Methods and limitations',
  description:
    'How CoolRx produces its numbers, how the model was validated, and what the '
    + 'tool cannot tell you.',
};

export default function Page() {
  return <MethodsPage />;
}
