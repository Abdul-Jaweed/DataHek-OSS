import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2 font-mono text-[11px] font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        brand: 'border-brand/30 bg-brand-soft text-brand-strong',
        success: 'border-success/30 bg-success-soft text-success',
        warning: 'border-warning/30 bg-warning-soft text-warning',
        danger: 'border-danger/30 bg-danger-soft text-danger',
        neutral: 'border-border bg-surface-2 text-muted',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
);

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  /** Renders a 6px status dot inheriting the badge text color. */
  dot?: boolean;
}

export function Badge({ variant, dot = false, className, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

export { badgeVariants };
