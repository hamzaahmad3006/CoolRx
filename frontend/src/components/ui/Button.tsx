import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { Icon } from './Icon';
import type { IconName } from '@/constants';
import { cn } from '@/lib/cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  readonly variant?: ButtonVariant;
  readonly icon?: IconName;
  readonly iconPosition?: 'leading' | 'trailing';
  readonly children: ReactNode;
}

/**
 * 36px control height for high-density layouts, 4px radius, no shadow.
 * Hierarchy comes from fill and hairline borders (SRS §28.5).
 */
const VARIANT_CLASSES: Readonly<Record<ButtonVariant, string>> = {
  primary: 'bg-accent text-on-accent hover:bg-accent-hover border border-transparent',
  secondary: 'bg-card text-ink border border-line hover:bg-subtle',
  ghost: 'bg-transparent text-ink border border-transparent hover:bg-subtle',
  danger: 'bg-danger-bg text-danger border border-danger-line hover:bg-danger-bg/80',
};

export function Button({
  variant = 'secondary',
  icon,
  iconPosition = 'leading',
  children,
  className,
  type = 'button',
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled}
      className={cn(
        // `whitespace-nowrap` and `shrink-0`: a label is not a paragraph. In a
        // tight flex row "Optimize plan" broke across two lines and then spilled
        // out of the fixed `h-9`, so the button rendered outside its own card.
        // `min-h-9` keeps the height where it was without capping it.
        'inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-sharp px-4',
        'whitespace-nowrap text-caption font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        VARIANT_CLASSES[variant],
        className,
      )}
      {...rest}
    >
      {icon !== undefined && iconPosition === 'leading' ? <Icon name={icon} /> : null}
      {children}
      {icon !== undefined && iconPosition === 'trailing' ? <Icon name={icon} /> : null}
    </button>
  );
}
