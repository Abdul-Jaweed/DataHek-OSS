import { useEffect, useRef, useState } from 'react';
import { api, streamAsk } from '../api/client';
import type { Connection, StreamEvent } from '../api/types';
import { Composer } from '../components/chat/Composer';
import { MessageBubble, type Message } from '../components/chat/MessageBubble';
import { EmptyState } from '../components/ui/EmptyState';
import { Button } from '../components/ui/Button';

function eventToMessage(ev: StreamEvent, message: Message): Partial<Message> {
  switch (ev.type) {
    case 'token':
      return { content: message.content + ev.content };
    case 'rows':
      return { columns: ev.columns, rows: ev.rows, rowCount: ev.row_count, truncated: ev.truncated };
    case 'clarification':
      return { content: ev.text, clarification: true };
    case 'done':
      return { streaming: false };
    default:
      return {};
  }
}

export function ChatPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listConnections().then((conns) => {
      setConnections(conns);
      if (conns.length > 0) setSelectedId((prev) => prev ?? conns[0].id);
    }).catch(() => setConnections([]));
  }, []);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  const send = async (text: string) => {
    if (!selectedId) return;
    let convId = conversationId;
    if (!convId) {
      try {
        const conv = await api.createConversation();
        convId = conv.id;
        setConversationId(convId);
      } catch { /* fall through */ }
    }

    const assistantId = `a-${Date.now()}`;
    setMessages((m) => [
      ...m,
      { id: `u-${Date.now()}`, role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '', streaming: true },
    ]);
    setStreaming(true);

    try {
      for await (const ev of streamAsk(text, selectedId, convId ?? undefined)) {
        setMessages((m) => m.map((msg) => (msg.id === assistantId ? { ...msg, ...eventToMessage(ev, msg) } : msg)));
      }
    } catch (err) {
      setMessages((m) =>
        m.map((msg) =>
          msg.id === assistantId
            ? { ...msg, streaming: false, error: true, content: err instanceof Error ? err.message : String(err) }
            : msg,
        ),
      );
    } finally {
      setStreaming(false);
    }
  };

  const newConversation = () => {
    setMessages([]);
    setConversationId(null);
  };

  if (connections.length === 0) {
    return (
      <EmptyState
        title="No connections yet"
        description="Connect a database to start asking questions in natural language."
        actionLabel="Add a connection"
      />
    );
  }

  return (
    <div className="chat-page">
      <div className="chat-toolbar">
        <select
          className="conn-select mono"
          value={selectedId ?? ''}
          onChange={(e) => setSelectedId(e.target.value || null)}
          aria-label="Connection"
        >
          {connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} · {c.provider}
            </option>
          ))}
        </select>
        {conversationId && <span className="caption conn-caption">conv {conversationId.slice(-8)}</span>}
        <Button variant="ghost" size="sm" onClick={newConversation} disabled={streaming}>
          New conversation
        </Button>
      </div>
      <div className="thread" ref={threadRef} aria-live="polite">
        {messages.length === 0 && (
          <p className="muted thread-welcome">
            Ask anything about your data. Follow-ups keep context.
          </p>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
      </div>
      <Composer hasConnection={!!selectedId} streaming={streaming} onSend={send} />
    </div>
  );
}