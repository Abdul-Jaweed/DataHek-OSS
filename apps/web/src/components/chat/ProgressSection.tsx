import { Check, CircleNotch } from '@phosphor-icons/react';
import { cn } from '../../lib/utils';

export interface ProgressState {
  stage: string;
  message: string;
}

const STAGES: { key: string; label: string }[] = [
  { key: 'connecting', label: 'Connecting' },
  { key: 'planning', label: 'Planning' },
  { key: 'executing', label: 'Executing' },
  { key: 'explaining', label: 'Explaining' },
];

export function ProgressSection({ progress }: { progress: ProgressState }) {
  const currentIdx = STAGES.findIndex((s) => s.key === progress.stage);
  const done = progress.stage === 'done';
  const idx = done ? STAGES.length - 1 : Math.max(currentIdx, 0);

  return (
    <div
      className="border-b border-border bg-surface px-4 py-2.5 sm:px-6"
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {STAGES.map((s, i) => {
          const isActive = !done && i === idx;
          const isDone = done || i < idx;
          return (
            <span
              key={s.key}
              className={cn(
                'flex items-center gap-1.5 text-xs font-medium transition-colors duration-200',
                isDone ? 'text-brand-strong' : isActive ? 'text-foreground' : 'text-faint',
              )}
            >
              {isActive ? (
                <CircleNotch size={13} weight="bold" className="animate-spin text-brand-strong" />
              ) : isDone ? (
                <Check size={13} weight="bold" className="text-brand-strong" />
              ) : (
                <span className="h-3 w-3 rounded-full border border-border-strong" />
              )}
              {s.label}
            </span>
          );
        })}
        <span className="ml-auto font-mono text-[11px] text-faint">{progress.message}</span>
      </div>
    </div>
  );
}