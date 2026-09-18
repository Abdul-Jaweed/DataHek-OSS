import { useEffect, useRef, useState } from 'react';
import { ArrowsClockwise } from '@phosphor-icons/react';
import type { StreamEvent } from '../api/types';
import { streamAsk } from '../api/client';
import { Composer } from '../components/chat/Composer';
import { MessageBubble, type Message } from '../components/chat/MessageBubble';
import { ProgressSection, type ProgressState } from '../components/chat/ProgressSection';
import { EmptyState } from '../components/ui/empty-state';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { ensureConversation, useStore } from '../store/use-store';

function applyEvent(ev: StreamEvent, message: Message): Partial<Message> {
  switch (ev.type) {
    case 'token':
      return { content: message.content + ev.content };
    case 'rows':
      return { columns: ev.columns, rows: ev.rows, rowCount: ev.row_count, truncated: ev.truncated };
    case 'clarification':
      return { content: ev.text, clarification: true, streaming: false };
    case 'verification':
      return { verified: { ok: ev.ok, note: ev.note } };
    case 'redactions':
      return { redactions: ev.categories };
    case 'suggestions':
      return { suggestions: ev.items };
    case 'steps':
      return { steps: ev.steps };
    case 'done':
      return { streaming: false };
    default:
      return {};
  }
}

export function ChatPage() {
  const { connections, selectedConnectionId, loadConnections, selectConnection, messages, streaming, setStreaming, appendMessage, patchMessage, newConversation } = useStore();
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadConnections();
  }, [loadConnections]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  const send = async (text: string) => {
    if (!selectedConnectionId) return;
    const convId = await ensureConversation();

    const assistantId = `a-${Date.now()}`;
    appendMessage({ id: `u-${Date.now()}`, role: 'user', content: text, at: Date.now() });
    appendMessage({ id: assistantId, role: 'assistant', content: '', streaming: true, at: Date.now() });
    setStreaming(true);

    try {
      for await (const ev of streamAsk(text, selectedConnectionId, convId ?? undefined)) {
        if (ev.type === 'progress') {
          setProgress({ stage: ev.stage, message: ev.message });
          continue;
        }
        if (ev.type === 'error') {
          setProgress(null);
          patchMessage(assistantId, () => ({ streaming: false, error: true, content: ev.message }));
          continue;
        }
        if (ev.type === 'done') setProgress(null);
        patchMessage(assistantId, (m) => applyEvent(ev, m));
      }
    } catch (err) {
      const code = (err as { code?: string } | null)?.code;
      if (code === 'CONNECTION_NOT_FOUND') {
        useStore.getState().selectConnection(null);
        void useStore.getState().loadConnections();
      }
      patchMessage(assistantId, () => ({
        streaming: false,
        error: true,
        content: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setStreaming(false);
    }
  };

  if (connections.length === 0) {
    return (
      <div className="p-6 sm:p-10">
        <EmptyState
          title="No connections yet"
          description="Connect a database to start asking questions in natural language."
        />
      </div>
    );
  }

  const selected = connections.find((c) => c.id === selectedConnectionId);
  let promptNo = 0;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border bg-surface">
        <div className="mx-auto flex w-full max-w-[1060px] flex-wrap items-center gap-3 px-4 py-2.5 sm:px-6">
          <label className="kicker text-faint" htmlFor="target-db">
            Target DB:
          </label>
          <select
            id="target-db"
            className="h-8 max-w-[260px] cursor-pointer rounded-md border border-border bg-surface-2 px-2 font-mono text-[12px] font-semibold text-foreground transition-colors duration-150 hover:border-border-strong"
            value={selectedConnectionId ?? ''}
            onChange={(e) => selectConnection(e.target.value || null)}
          >
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.provider}
              </option>
            ))}
          </select>
          <Badge variant={selectedConnectionId ? 'success' : 'neutral'} dot>
            {selectedConnectionId ? 'read-only mode' : 'no connection'}
          </Badge>
          <div className="ml-auto">
            <Button
              variant="secondary"
              size="sm"
              icon={<ArrowsClockwise size={14} />}
              onClick={newConversation}
              disabled={streaming}
            >
              <span className="hidden sm:inline">New conversation</span>
            </Button>
          </div>
        </div>
      </div>

      {progress && <ProgressSection progress={progress} />}

      <div ref={threadRef} className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
        <div className="mx-auto w-full max-w-[1060px] space-y-4 px-4 py-4 sm:px-6">
          {messages.length === 0 && (
            <div className="pt-16 text-center">
              <p className="kicker text-faint">No messages yet</p>
              <p className="mt-2 text-[13px] text-muted">
                Ask anything about your data. Follow-ups keep context.
              </p>
            </div>
          )}
          {messages.map((m) => {
            if (m.role === 'user') promptNo += 1;
            return (
              <MessageBubble
                key={m.id}
                message={m}
                index={m.role === 'user' ? promptNo : undefined}
                onSuggestion={streaming ? undefined : send}
              />
            );
          })}
        </div>
      </div>

      <Composer connectionName={selected?.name ?? null} streaming={streaming} onSend={send} />
    </div>
  );
}
