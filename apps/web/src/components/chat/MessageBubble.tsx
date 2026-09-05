import type { ReactNode } from 'react';

export type MessageRole = 'user' | 'assistant';

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  streaming?: boolean;
  columns?: string[];
  rows?: Record<string, unknown>[];
  rowCount?: number;
  truncated?: boolean;
  error?: boolean;
  clarification?: boolean;
}

export interface MessageBubbleProps {
  message: Message;
  actions?: ReactNode;
}

export function MessageBubble({ message, actions }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={[
          'max-w-[75%] rounded-lg px-4 py-3 text-sm leading-relaxed sm:max-w-[85%]',
          isUser
            ? 'bg-user text-user-contrast'
            : message.error
              ? 'border border-danger bg-danger-soft text-danger'
              : message.clarification
                ? 'border border-brand bg-brand-soft text-brand-strong'
                : 'border border-border bg-surface text-foreground',
        ].join(' ')}
      >
        <div className="whitespace-pre-wrap">
          {message.content}
          {message.streaming && <span className="animate-pulse text-brand-strong">▍</span>}
        </div>

        {message.columns && message.rows && (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full border-collapse font-mono text-xs">
              <thead>
                <tr>
                  {message.columns.map((c) => (
                    <th key={c} className="border-b border-border-strong px-2 py-1 text-left font-medium text-brand-strong">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {message.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-surface-2">
                    {message.columns!.map((c) => (
                      <td key={c} className="border-b border-border px-2 py-1">
                        {String(row[c] ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {message.rowCount !== undefined && (
          <div className="mt-2 font-mono text-[11px] text-muted">
            {message.rowCount} row{message.rowCount === 1 ? '' : 's'}
            {message.truncated ? ' · truncated' : ''}
          </div>
        )}

        {actions && <div className="mt-2 flex gap-2">{actions}</div>}
      </div>
    </div>
  );
}