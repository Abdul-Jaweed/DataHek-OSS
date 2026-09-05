import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-mono text-xs font-medium transition-colors',
  {
    variants: {
variant: {
        brand: 'border-brand/40 bg-brand-soft text-brand-strong',
        success: 'border-success/40 bg-success-soft text-success',
        warning: 'border-warning bg-warning-soft text-warning',
        danger: 'border-danger bg-danger-soft text-danger',
        neutral: 'border-border-strong bg-surface-2 text-muted',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
);

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ variant, className, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}