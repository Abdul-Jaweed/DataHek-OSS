import { PaperPlaneRight } from '@phosphor-icons/react';
import { useState } from 'react';

export interface ComposerProps {
  connectionName?: string | null;
  streaming: boolean;
  onSend: (text: string) => void;
}

export function Composer({ connectionName, streaming, onSend }: ComposerProps) {
  const [text, setText] = useState('');
  const hasConnection = !!connectionName;
  const canSend = hasConnection && text.trim().length > 0 && !streaming;

  const send = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText('');
  };

  return (
    <div className="border-t border-border bg-background px-4 py-3 sm:px-6">
      <div className="mx-auto w-full max-w-[1060px]">
        <div className="overflow-hidden rounded-lg border border-border bg-surface transition-colors duration-150 focus-within:border-border-strong">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={
              hasConnection
                ? 'Ask anything about your data… (Enter to send, Shift+Enter for newline)'
                : 'Select a connection first'
            }
            rows={2}
            className="w-full resize-none bg-transparent px-4 py-3 text-[13.5px] leading-relaxed text-foreground outline-none placeholder:text-faint disabled:opacity-50"
            aria-label="Question"
            disabled={!hasConnection}
          />
          <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              {hasConnection ? (
                <span className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-foreground">
                  <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
                  <span className="truncate">{connectionName}</span>
                </span>
              ) : (
                <span className="font-mono text-[11px] text-faint">No connection selected</span>
              )}
              <span className="hidden font-mono text-[11px] text-faint sm:inline">
                Enter to send · Shift+Enter for newline
              </span>
            </div>
            <button
              className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md bg-brand px-3 text-[12px] font-semibold text-brand-contrast transition-colors duration-150 hover:bg-brand-hover disabled:pointer-events-none disabled:opacity-40"
              onClick={send}
              disabled={!canSend}
              aria-label="Send"
              aria-busy={streaming}
            >
              {streaming ? (
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
              ) : (
                <PaperPlaneRight size={14} weight="bold" />
              )}
              Send
              <kbd className="rounded-sm bg-black/15 px-1 font-mono text-[9px] leading-4">↵</kbd>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
