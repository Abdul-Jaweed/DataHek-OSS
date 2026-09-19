import { PaperPlaneRight, Terminal } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import type { Prompt } from '../../api/types';

export interface ComposerProps {
  connectionName?: string | null;
  streaming: boolean;
  onSend: (text: string) => void;
}

export function Composer({ connectionName, streaming, onSend }: ComposerProps) {
  const [text, setText] = useState('');
  const [prompts, setPrompts] = useState<Prompt[] | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const hasConnection = !!connectionName;
  const canSend = hasConnection && text.trim().length > 0 && !streaming;

  useEffect(() => {
    if (!pickerOpen) return;
    const onPointerDown = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setPickerOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPickerOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [pickerOpen]);

  useEffect(() => {
    if (pickerOpen && prompts === null) {
      api.listPrompts().then(setPrompts).catch(() => setPrompts([]));
    }
  }, [pickerOpen, prompts]);

  const applyPrompt = (p: Prompt) => {
    setText(p.content);
    setPickerOpen(false);
    textareaRef.current?.focus();
  };

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
            ref={textareaRef}
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
              <div className="relative" ref={pickerRef}>
                <button
                  className="inline-flex cursor-pointer items-center gap-1 rounded-sm px-2 py-0.5 font-mono text-[11px] text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-foreground"
                  onClick={() => setPickerOpen((v) => !v)}
                  aria-haspopup="listbox"
                  aria-expanded={pickerOpen}
                >
                  <Terminal size={13} className="text-brand-strong" />
                  Prompt templates
                </button>
                {pickerOpen && (
                  <div
                    className="absolute bottom-full left-0 z-20 mb-1.5 max-h-64 w-80 overflow-y-auto rounded-sm border border-border bg-surface shadow-lg"
                    role="listbox"
                    aria-label="Saved prompts"
                  >
                    {prompts === null ? (
                      <div className="px-3 py-2 font-mono text-[11px] text-faint">Loading…</div>
                    ) : prompts.length === 0 ? (
                      <div className="px-3 py-2 font-mono text-[11px] text-faint">No saved prompts</div>
                    ) : (
                      prompts.map((p) => (
                        <button
                          key={p.id}
                          className="block w-full cursor-pointer border-b border-border px-3 py-2 text-left transition-colors duration-150 last:border-b-0 hover:bg-surface-2"
                          onClick={() => applyPrompt(p)}
                          role="option"
                          aria-selected={false}
                        >
                          <span className="block font-mono text-[12px] font-semibold text-foreground">
                            {p.name}
                          </span>
                          <span className="mt-0.5 block truncate text-[11px] text-muted">{p.content}</span>
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>
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
