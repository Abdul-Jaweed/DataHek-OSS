import { useEffect, useRef } from 'react';
import { Plus } from '@phosphor-icons/react';
import type { StreamEvent } from '../api/types';
import { streamAsk } from '../api/client';
import { Composer } from '../components/chat/Composer';
import { MessageBubble, type Message } from '../components/chat/MessageBubble';
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
    case 'done':
      return { streaming: false };
    default:
      return {};
  }
}

export function ChatPage() {
  const { connections, selectedConnectionId, loadConnections, selectConnection, messages, streaming, setStreaming, appendMessage, patchMessage, newConversation } = useStore();
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
    appendMessage({ id: `u-${Date.now()}`, role: 'user', content: text });
    appendMessage({ id: assistantId, role: 'assistant', content: '', streaming: true });
    setStreaming(true);

    try {
      for await (const ev of streamAsk(text, selectedConnectionId, convId ?? undefined)) {
        patchMessage(assistantId, (m) => applyEvent(ev, m));
      }
    } catch (err) {
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

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3 sm:px-6">
        <select
          className="h-9 cursor-pointer rounded-md border border-border bg-surface px-3 font-mono text-sm text-foreground focus:outline-none focus:border-brand"
          value={selectedConnectionId ?? ''}
          onChange={(e) => selectConnection(e.target.value || null)}
          aria-label="Connection"
        >
          {connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} · {c.provider}
            </option>
          ))}
        </select>
        <Badge variant="neutral" className="hidden sm:inline-flex">
          {selectedConnectionId ? 'read-only' : 'no connection'}
        </Badge>
        <div className="ml-auto">
          <Button variant="ghost" size="sm" icon={<Plus size={16} />} onClick={newConversation} disabled={streaming}>
            <span className="hidden sm:inline">New</span>
          </Button>
        </div>
      </div>

      <div ref={threadRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-6" aria-live="polite">
        {messages.length === 0 && (
          <p className="pt-16 text-center text-sm text-muted">
            Ask anything about your data. Follow-ups keep context.
          </p>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
      </div>

      <Composer hasConnection={!!selectedConnectionId} streaming={streaming} onSend={send} />
    </div>
  );
}