import { ChartBar, DownloadSimple, Table } from '@phosphor-icons/react';
import { useState } from 'react';
import { ResultChart, shouldChart } from './ResultChart';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ReactNode } from 'react';

export type MessageRole = 'user' | 'assistant';

export interface MessageStep {
  question: string;
  row_count: number | null;
  sql: string | null;
}

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
  verified?: { ok: boolean; note: string };
  redactions?: string[];
  steps?: MessageStep[];
}

export interface MessageBubbleProps {
  message: Message;
  actions?: ReactNode;
}

function csvEscape(value: unknown): string {
  const text =
    value === null || value === undefined
      ? ''
      : typeof value === 'object'
        ? JSON.stringify(value)
        : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function downloadCsv(columns: string[], rows: Record<string, unknown>[]): void {
  const header = columns.map(csvEscape).join(',');
  const body = rows.map((row) => columns.map((c) => csvEscape(row[c])).join(',')).join('\n');
  const blob = new Blob([`\uFEFF${header}\n${body}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `datahek-results-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function MessageBubble({ message, actions }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const chartable =
    !isUser && !!message.columns && !!message.rows && shouldChart(message.columns, message.rows);
  const [showChart, setShowChart] = useState(chartable);

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
        {isUser || message.error ? (
          <div className="whitespace-pre-wrap">
            {message.content}
            {message.streaming && <span className="animate-pulse text-brand-strong">▍</span>}
          </div>
        ) : (
          <div className="md">
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
            {message.streaming && <span className="animate-pulse text-brand-strong">▍</span>}
          </div>
        )}

        {message.steps && message.steps.length > 0 && (
          <div className="mt-3 border-t border-border pt-2">
            <div className="font-mono text-[10px] uppercase tracking-wider text-muted">
              multi-step analysis · {message.steps.length} queries
            </div>
            <ol className="mt-1.5 space-y-1">
              {message.steps.map((step, i) => (
                <li key={i} className="flex items-baseline gap-2 font-mono text-[11px] text-muted">
                  <span className="text-brand-strong">{i + 1}.</span>
                  <span className="truncate">{step.question}</span>
                  {step.row_count !== null && <span className="text-faint">({step.row_count} rows)</span>}
                </li>
              ))}
            </ol>
          </div>
        )}

        {message.redactions && message.redactions.length > 0 && (
          <div className="mt-1 font-mono text-[11px] text-warning">
            ⚠ redacted: {message.redactions.join(', ')}
          </div>
        )}

        {chartable && showChart && message.columns && message.rows && (
          <ResultChart columns={message.columns} rows={message.rows} />
        )}

        {message.columns && message.rows && (!chartable || !showChart) && (
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

        {(message.rowCount !== undefined || (message.columns && message.rows)) && (
          <div className="mt-2 flex items-center gap-3 font-mono text-[11px] text-muted">
            {message.rowCount !== undefined && (
              <span>
                {message.rowCount} row{message.rowCount === 1 ? '' : 's'}
                {message.truncated ? ' · truncated' : ''}
              </span>
            )}
            {message.columns && message.rows && message.rows.length > 0 && (
              <button
                className="flex cursor-pointer items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted transition-colors hover:border-border-strong hover:text-foreground"
                onClick={() => downloadCsv(message.columns!, message.rows!)}
                aria-label="Export results as CSV"
              >
                <DownloadSimple size={11} /> CSV
              </button>
            )}
            {chartable && (
              <button
                className="flex cursor-pointer items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted transition-colors hover:border-border-strong hover:text-foreground"
                onClick={() => setShowChart((v) => !v)}
                aria-label={showChart ? 'Show table' : 'Show chart'}
              >
                {showChart ? <Table size={11} /> : <ChartBar size={11} />}
                {showChart ? 'Table' : 'Chart'}
              </button>
            )}
          </div>
        )}

        {message.verified && (
          <div
            className={`mt-1 flex items-center gap-1.5 font-mono text-[11px] ${
              message.verified.ok ? 'text-success' : 'text-warning'
            }`}
          >
            {message.verified.ok ? '✓' : '⚠'} verified
            {message.verified.note ? ` · ${message.verified.note}` : ''}
          </div>
        )}

        {actions && <div className="mt-2 flex gap-2">{actions}</div>}
      </div>
    </div>
  );
}
