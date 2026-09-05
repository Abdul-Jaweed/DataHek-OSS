import { useEffect, useState } from 'react';
import { ChatCircleText, ClockCounterClockwise } from '@phosphor-icons/react';
import { api } from '../api/client';
import type { Conversation } from '../api/types';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { Skeleton } from '../components/ui/skeleton';
import { useNavigate } from 'react-router-dom';

export function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.createConversation('probe')
      .then(() => api.getConversation('__list__'))
      .catch(() => setConversations([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-5xl p-6 sm:p-10">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">Conversations</h1>
        <p className="text-sm text-muted">Multi-turn sessions persisted in SQLite</p>
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
              <p className="truncate text-sm font-semibold text-foreground">{c.title ?? 'Untitled'}</p>
              <p className="mt-0.5 truncate font-mono text-xs text-muted">
                {c.messages.length} message{c.messages.length === 1 ? '' : 's'} · {c.id.slice(-8)}
              </p>
            </div>
            <Button variant="ghost" size="sm" icon={<ChatCircleText size={16} />} onClick={() => navigate('/chat')}>
              Open
            </Button>
          </Card>
        ))}
      </div>
    </div>
  );
}