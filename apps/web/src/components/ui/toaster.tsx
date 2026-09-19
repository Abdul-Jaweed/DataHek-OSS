import { CheckCircle, XCircle } from '@phosphor-icons/react';
import { useToastStore } from '../../lib/toast';

export function Toaster() {
  const { toasts, dismiss } = useToastStore();
  if (toasts.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-20 left-1/2 z-50 flex w-max -translate-x-1/2 flex-col items-center gap-1.5"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <button
          key={t.id}
          onClick={() => dismiss(t.id)}
          className="pointer-events-auto flex cursor-pointer items-center gap-2 rounded-sm border border-border-strong bg-foreground px-3.5 py-1.5 font-mono text-xs text-background shadow-md"
        >
          {t.icon === 'error' ? (
            <XCircle size={14} weight="bold" />
          ) : (
            <CheckCircle size={14} weight="bold" />
          )}
          {t.message}
        </button>
      ))}
    </div>
  );
}
