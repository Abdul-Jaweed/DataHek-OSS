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
  const cls = ['msg', `msg-${message.role}`];
  if (message.error) cls.push('msg-error');
  if (message.clarification) cls.push('msg-clarification');

  return (
    <div className={cls.join(' ')}>
      <div className="msg-content">
        {message.content}
        {message.streaming && <span className="caret" aria-hidden="true">▍</span>}
      </div>
      {message.columns && message.rows && (
        <table className="msg-table mono">
          <thead>
            <tr>
              {message.columns.map((c) => (
                <th key={c} scope="col">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {message.rows.map((row, i) => (
              <tr key={i}>
                {message.columns!.map((c) => (
                  <td key={c}>{String(row[c] ?? '')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {message.rowCount !== undefined && (
        <div className="msg-meta mono">
          {message.rowCount} row{message.rowCount === 1 ? '' : 's'}
          {message.truncated ? ' · truncated' : ''}
        </div>
      )}
      {actions && <div className="msg-actions">{actions}</div>}
    </div>
  );
}