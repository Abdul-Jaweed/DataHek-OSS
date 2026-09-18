import { Check } from '@phosphor-icons/react';
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
      className="border-b border-border bg-surface px-4 py-2 sm:px-6"
      role="status"
      aria-live="polite"
    >
      <div className="mx-auto flex w-full max-w-[1060px] flex-wrap items-center gap-2">
        {STAGES.map((s, i) => {
          const state = done || i < idx ? 'done' : i === idx ? 'active' : 'pending';
          return (
            <div key={s.key} className="flex items-center gap-2">
              {i > 0 && <span className="font-mono text-[11px] text-faint">→</span>}
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-[11px] transition-colors duration-200',
                  state === 'done' && 'border-success/30 bg-success-soft text-success',
                  state === 'active' && 'border-brand/30 bg-brand-soft font-semibold text-brand-strong',
                  state === 'pending' && 'border-border bg-surface-2 text-faint',
                )}
              >
                {state === 'done' ? (
                  <Check size={11} weight="bold" />
                ) : (
                  <span
                    className={cn('h-1.5 w-1.5 rounded-full', state === 'active' ? 'animate-pulse bg-current' : 'bg-current opacity-40')}
                  />
                )}
                {s.label}
              </span>
            </div>
          );
        })}
        <span className="ml-auto font-mono text-[11px] text-faint">{progress.message}</span>
      </div>
    </div>
  );
}
