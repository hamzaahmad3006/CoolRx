'use client';

import { useId, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface TooltipProps {
  /** Explanation text. Plain language — see `GLOSSARY` in `@/constants`. */
  readonly content: string;
  readonly children: ReactNode;
  readonly side?: 'top' | 'bottom';
  readonly className?: string;
}

/**
 * Dark tooltip, 13px, 4px radius, no arrow tail (SRS §28.5).
 *
 * CSS-only on hover and focus-within, so it needs no positioning library and
 * works before hydration. `aria-describedby` links it to the trigger so screen
 * readers get the explanation rather than nothing.
 */
export function Tooltip({
  content,
  children,
  side = 'top',
  className,
}: TooltipProps) {
  const id = useId();

  return (
    <span className={cn('group/tt relative inline-flex items-center', className)}>
      <span aria-describedby={id} className="inline-flex items-center">
        {children}
      </span>

      <span
        id={id}
        role="tooltip"
        className={cn(
          'pointer-events-none absolute left-1/2 z-50 w-max max-w-xs -translate-x-1/2',
          'rounded-sharp bg-inverse px-2 py-1.5 text-caption text-on-inverse',
          // `invisible` matters as much as `opacity-0`: without it the tooltip
          // text stays in the accessibility tree and in text selection, so a
          // table cell's copied value would carry the explanation with it.
          'invisible opacity-0 transition-opacity duration-100',
          'group-hover/tt:visible group-hover/tt:opacity-100',
          'group-focus-within/tt:visible group-focus-within/tt:opacity-100',
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
        )}
      >
        {content}
      </span>
    </span>
  );
}
