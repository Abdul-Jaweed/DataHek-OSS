import { Database } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { Button } from './button';

export interface EmptyStateProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: ReactNode;
}

export function EmptyState({ title, description, actionLabel, onAction, icon }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-sm border border-border bg-surface text-faint [&_svg]:h-5 [&_svg]:w-5">
        {icon ?? <Database size={20} weight="regular" />}
      </div>
      <h3 className="text-[15px] font-bold text-foreground">{title}</h3>
      {description && <p className="mt-2 max-w-sm text-[12.5px] leading-relaxed text-muted">{description}</p>}
      {actionLabel && onAction && (
        <Button className="mt-5" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
