import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'flex h-9 w-full rounded-md border border-border bg-surface px-3 py-1 text-sm text-foreground',
        'placeholder:text-faint focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/25',
        'disabled:opacity-50',
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'flex min-h-20 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground',
        'placeholder:text-faint focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/25',
        className,
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn('font-mono text-[11px] uppercase tracking-wider text-muted', className)}
      {...props}
    />
  );
}