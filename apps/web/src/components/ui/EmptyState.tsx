import { Inbox } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './Button';

export interface EmptyStateProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: ReactNode;
}

export function EmptyState({ title, description, actionLabel, onAction, icon }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon ?? <Inbox size={40} strokeWidth={1.5} />}</div>
      <h3>{title}</h3>
      {description && <p className="muted empty-desc">{description}</p>}
      {actionLabel && onAction && (
        <Button variant="primary" onClick={onAction} style={{ marginTop: 'var(--space-4)' }}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}