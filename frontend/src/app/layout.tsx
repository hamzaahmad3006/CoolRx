import type { Metadata, Viewport } from 'next';
import { Inter, JetBrains_Mono, Source_Serif_4 } from 'next/font/google';
import type { ReactNode } from 'react';

import { Providers } from '@/redux/Providers';
import { BRAND } from '@/constants';
import './globals.css';

/**
 * Fonts are self-hosted by next/font at build time — no runtime request to
 * Google Fonts, no font-swap flash. The CSS variable names match the tokens
 * declared in `globals.css`.
 */
const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-inter',
  display: 'swap',
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

const sourceSerif = Source_Serif_4({
  subsets: ['latin'],
  weight: ['400', '600'],
  variable: '--font-source-serif',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {
    default: `${BRAND.name} — ${BRAND.tagline}`,
    template: `%s · ${BRAND.name}`,
  },
  description: BRAND.heroSubline,
  applicationName: BRAND.name,
  openGraph: {
    title: `${BRAND.name} — ${BRAND.tagline}`,
    description: BRAND.heroSubline,
    type: 'website',
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#f7f7f5',
};

interface RootLayoutProps {
  readonly children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetBrainsMono.variable} ${sourceSerif.variable}`}
      suppressHydrationWarning
    >
      {/*
        `suppressHydrationWarning` on `body` for the same reason it is on `html`:
        extensions edit both before React attaches. Password managers and reader
        tools stamp an attribute on `body` — `__processed_<uuid>__="true"`, with a
        fresh uuid each load — and React reports the mismatch as a hydration
        error on every page. The warning is real but the cause is outside the
        app, and leaving it in place trains the reader to ignore the console,
        where a genuine mismatch would then also go unread. This suppresses
        attribute noise on this one element only; children still hydrate strictly.
      */}
      <body
        className="min-h-screen bg-canvas text-ink antialiased"
        suppressHydrationWarning
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
