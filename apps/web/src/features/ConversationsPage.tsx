import { useEffect, useState } from 'react';
import { ChatCircleText, ClockCounterClockwise } from '@phosphor-icons/react';
import { api } from '../api/client';
import type { ConversationSummary } from '../api/types';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { Skeleton } from '../components/ui/skeleton';
import { useNavigate } from 'react-router-dom';

function fmtUpdated(value?: string): string {
  return value ? value.slice(0, 19).replace('T', ' ') : '';
}

export function ConversationsPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .listConversations()
      .then((page) => {
        setConversations(page.items);
        setCursor(page.next_cursor);
      })
      .catch(() => setConversations([]))
      .finally(() => setLoading(false));
  }, []);

  const loadMore = async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await api.listConversations(cursor);
      setConversations((prev) => [...prev, ...page.items]);
      setCursor(page.next_cursor);
    } catch {
      /* keep the current page on failure */
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl p-6 sm:p-10">
      <div className="mb-6">
        <h1 className="text-[21px] font-extrabold tracking-[-0.02em] text-foreground">Conversations</h1>
        <p className="text-sm text-muted">Every saved chat session — inspect or continue in Chat</p>
      </div>

      {loading && (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}
        </div>
      )}

      {!loading && conversations.length === 0 && (
        <EmptyState
          title="No conversations yet"
          description="Start asking in Chat — every session is saved as a conversation."
          actionLabel="Go to chat"
          onAction={() => navigate('/chat')}
        />
      )}

      <div className="space-y-3">
        {conversations.map((c) => (
          <Card key={c.id} className="flex items-center gap-4 p-4">
            <div className="rounded-md bg-surface-2 p-2 text-brand-strong">
              <ClockCounterClockwise size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-foreground">{c.title ?? 'Untitled session'}</p>
              <p className="mt-0.5 truncate font-mono text-xs text-muted">
                {fmtUpdated(c.updated_at) && `${fmtUpdated(c.updated_at)} · `}
                {c.id.slice(-8)}
              </p>
            </div>
            <Button variant="ghost" size="sm" icon={<ChatCircleText size={16} />} onClick={() => navigate('/chat')}>
              Open
            </Button>
          </Card>
        ))}
      </div>

      {cursor && (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" loading={loadingMore} onClick={loadMore}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
