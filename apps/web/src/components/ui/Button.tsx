import { cva, type VariantProps } from 'class-variance-authority';
import { Spinner } from '@phosphor-icons/react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-semibold transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:pointer-events-none disabled:opacity-40 cursor-pointer',
  {
    variants: {
      variant: {
        default: 'bg-brand text-brand-contrast hover:bg-brand-hover',
        secondary: 'bg-surface-2 text-foreground border border-border hover:bg-surface hover:border-border-strong',
        ghost: 'text-muted hover:bg-surface-2 hover:text-foreground',
        outline: 'border border-border text-foreground hover:bg-surface-2',
        destructive: 'border border-danger text-danger hover:bg-danger-soft',
        link: 'text-brand-strong underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 px-3 text-xs',
        md: 'h-9 px-4 text-sm',
        lg: 'h-11 px-6 text-base',
        icon: 'h-9 w-9 p-0',
      },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({ variant, size, loading = false, icon, children, className, ...rest }: ButtonProps) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={rest.disabled || loading}
      aria-busy={loading}
      {...rest}
    >
      {loading ? <Spinner className="animate-spin" size={16} weight="bold" /> : icon}
      {children}
    </button>
  );
}

export { buttonVariants };