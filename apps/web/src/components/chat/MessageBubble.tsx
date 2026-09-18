import {
  ArrowRight,
  ChartBar,
  Check,
  CircleNotch,
  Code,
  Copy,
  DownloadSimple,
  Lightning,
  Table,
  User,
  Warning,
} from '@phosphor-icons/react';
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
  at?: number;
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
  suggestions?: string[];
}

export interface MessageBubbleProps {
  message: Message;
  /** 1-based ordinal of this prompt in the thread (user messages only). */
  index?: number;
  actions?: ReactNode;
  onSuggestion?: (text: string) => void;
}

type Tab = 'chart' | 'table' | 'sql';

function fmtTime(at?: number): string {
  return at ? `${new Date(at).toISOString().slice(11, 19)} UTC` : '';
}

function isNumeric(value: unknown): boolean {
  if (typeof value === 'number') return true;
  if (typeof value === 'string' && value.trim() !== '') {
    return Number.isFinite(Number(value.replace(/,/g, '')));
  }
  return false;
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

function StatusBadge({ message }: { message: Message }) {
  const base = 'inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2 font-mono text-[11px] font-medium uppercase tracking-wide whitespace-nowrap';
  if (message.error) {
    return (
      <span className={`${base} border-danger/30 bg-danger-soft text-danger`}>
        <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
        Execution failed
      </span>
    );
  }
  if (message.clarification) {
    return (
      <span className={`${base} border-brand/30 bg-brand-soft text-brand-strong`}>
        <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
        Needs input
      </span>
    );
  }
  if (message.streaming) {
    return (
      <span className={`${base} border-border bg-surface-2 text-muted`}>
        <CircleNotch size={11} weight="bold" className="animate-spin" />
        Running
      </span>
    );
  }
  if (message.verified && !message.verified.ok) {
    return (
      <span className={`${base} border-warning/30 bg-warning-soft text-warning`}>
        <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
        Unverified
      </span>
    );
  }
  return (
    <span className={`${base} border-success/30 bg-success-soft text-success`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      Execution ok
    </span>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
  badge?: ReactNode;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={[
        'inline-flex cursor-pointer items-center gap-1.5 rounded-sm border px-3 py-1 font-mono text-[12px] transition-colors duration-150',
        active
          ? 'border-border bg-surface font-semibold text-foreground'
          : 'border-transparent text-muted hover:bg-surface hover:text-foreground',
      ].join(' ')}
    >
      {icon}
      <span>{label}</span>
      {badge}
    </button>
  );
}

export function MessageBubble({ message, index, actions, onSuggestion }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const hasData = !!message.columns && !!message.rows;
  const sqlSteps = (message.steps ?? []).filter((s) => s.sql);
  const chartable = !isUser && hasData && shouldChart(message.columns!, message.rows!);
  const [tab, setTab] = useState<Tab>(chartable ? 'chart' : sqlSteps.length > 0 ? 'sql' : 'table');
  const [copied, setCopied] = useState(false);

  const effectiveTab: Tab =
    tab === 'chart' && !chartable ? (hasData ? 'table' : sqlSteps.length > 0 ? 'sql' : 'table') : tab;
  const time = fmtTime(message.at);

  const copySql = async () => {
    try {
      await navigator.clipboard.writeText(sqlSteps.map((s) => s.sql).join('\n\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  if (isUser) {
    return (
      <article className="w-full rounded-lg border border-border bg-surface">
        <div className="flex items-center gap-3 px-3.5 py-3">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm border border-border bg-surface-2 text-muted">
            <User size={13} />
          </div>
          <div className="kicker flex shrink-0 items-center gap-2">
            <span className="font-bold text-foreground">Data operator</span>
            {time && (
              <>
                <span className="text-faint">·</span>
                <span className="text-muted">{time}</span>
              </>
            )}
          </div>
          <div className="hidden h-3 w-px shrink-0 bg-border sm:block" aria-hidden />
          <p className="min-w-0 flex-1 whitespace-pre-wrap text-[13.5px] leading-relaxed text-foreground">
            {message.content}
          </p>
          {index !== undefined && (
            <span className="hidden shrink-0 rounded-sm border border-border bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-muted sm:inline">
              Prompt #{String(index).padStart(2, '0')}
            </span>
          )}
        </div>
      </article>
    );
  }

  const showArtifact = hasData || sqlSteps.length > 0 || (message.steps?.length ?? 0) > 0;

  return (
    <article className="w-full overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-brand text-brand-contrast">
            <Lightning size={13} weight="bold" />
          </div>
          <div className="kicker flex min-w-0 items-center gap-2">
            <span className="font-bold text-foreground">DataHek Analyst</span>
            {time && (
              <>
                <span className="text-faint">·</span>
                <span className="truncate text-muted">{time}</span>
              </>
            )}
          </div>
        </div>
        <StatusBadge message={message} />
      </div>

      {showArtifact && (
        <div className="border-b border-border">
          {(hasData || sqlSteps.length > 0) && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface-2 px-3.5 py-2">
              <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Result views">
                {chartable && (
                  <TabButton
                    active={effectiveTab === 'chart'}
                    onClick={() => setTab('chart')}
                    icon={<ChartBar size={14} />}
                    label="Chart view"
                  />
                )}
                {hasData && (
                  <TabButton
                    active={effectiveTab === 'table'}
                    onClick={() => setTab('table')}
                    icon={<Table size={14} />}
                    label={`Data table${message.rowCount !== undefined ? ` (${message.rowCount.toLocaleString()} rows)` : ''}`}
                  />
                )}
                {sqlSteps.length > 0 && (
                  <TabButton
                    active={effectiveTab === 'sql'}
                    onClick={() => setTab('sql')}
                    icon={<Code size={14} />}
                    label="SQL"
                  />
                )}
              </div>
              {hasData && message.rows && message.rows.length > 0 && (
                <button
                  className="inline-flex cursor-pointer items-center gap-1 rounded-sm border border-border bg-surface px-2.5 py-1 font-mono text-[11.5px] font-semibold text-foreground transition-colors duration-150 hover:border-border-strong hover:bg-surface-2"
                  onClick={() => downloadCsv(message.columns!, message.rows!)}
                  aria-label="Export results as CSV"
                >
                  <DownloadSimple size={14} className="text-brand-strong" />
                  Export CSV
                </button>
              )}
            </div>
          )}

          {effectiveTab === 'chart' && chartable && message.columns && message.rows && (
            <div className="bg-surface p-3.5">
              <div className="rounded-md border border-border bg-surface-2/50 p-2">
                <ResultChart columns={message.columns} rows={message.rows} />
              </div>
            </div>
          )}

          {effectiveTab === 'table' && hasData && message.columns && message.rows && (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left" aria-label="Query results">
                <thead>
                  <tr className="h-9 border-b border-border bg-surface-2">
                    {message.columns.map((c) => (
                      <th
                        key={c}
                        className={[
                          'kicker px-3.5 font-medium text-muted',
                          message.rows!.every((r) => isNumeric(r[c]) || r[c] === null) ? 'text-right' : '',
                        ].join(' ')}
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="font-mono text-[12px]">
                  {message.rows.map((row, i) => (
                    <tr key={i} className="h-9 border-b border-border last:border-b-0 hover:bg-surface-2/60">
                      {message.columns!.map((c) => (
                        <td
                          key={c}
                          className={[
                            'px-3.5 text-foreground',
                            message.rows!.every((r) => isNumeric(r[c]) || r[c] === null)
                              ? 'text-right tabular-nums'
                              : '',
                          ].join(' ')}
                        >
                          {String(row[c] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-between gap-3 border-t border-border bg-surface-2 px-3.5 py-2 font-mono text-[11px] text-muted">
                <span>
                  Showing {message.rows.length.toLocaleString()} of{' '}
                  {(message.rowCount ?? message.rows.length).toLocaleString()} rows
                  {message.truncated ? ' · truncated' : ''}
                </span>
                {message.redactions && message.redactions.length > 0 && <span>Masked fields: {message.redactions.length}</span>}
              </div>
            </div>
          )}

          {effectiveTab === 'sql' && sqlSteps.length > 0 && (
            <div className="bg-surface-2">
              <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2">
                <div className="flex items-center gap-2">
                  <Code size={14} className="text-brand-strong" />
                  <span className="kicker text-muted">Executed SQL</span>
                  {sqlSteps.length > 1 && (
                    <span className="font-mono text-[11px] text-faint">{sqlSteps.length} statements</span>
                  )}
                </div>
                <button
                  className="inline-flex cursor-pointer items-center gap-1 rounded-sm border border-border bg-surface px-2 py-0.5 font-mono text-[11px] text-muted transition-colors duration-150 hover:border-border-strong hover:text-foreground"
                  onClick={copySql}
                  aria-label="Copy SQL"
                >
                  {copied ? <Check size={12} weight="bold" /> : <Copy size={12} />}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              {sqlSteps.map((step, i) => (
                <div key={i} className={i > 0 ? 'border-t border-border' : undefined}>
                  {sqlSteps.length > 1 && (
                    <div className="px-3.5 pt-2.5 font-mono text-[11px] text-faint">
                      {i + 1}. {step.question}
                    </div>
                  )}
                  <pre className="overflow-x-auto p-3.5 font-mono text-[12px] leading-relaxed text-foreground">
                    <code>{step.sql}</code>
                  </pre>
                </div>
              ))}
            </div>
          )}

          {(message.steps?.length ?? 0) > 1 && (
            <div className="border-t border-border px-3.5 py-2.5">
              <div className="kicker mb-1.5 text-faint">Multi-step analysis · {message.steps!.length} queries</div>
              <ol className="space-y-1">
                {message.steps!.map((step, i) => (
                  <li key={i} className="flex items-baseline gap-2 font-mono text-[11px] text-muted">
                    <span className="text-brand-strong">{i + 1}.</span>
                    <span className="truncate">{step.question}</span>
                    {step.row_count !== null && <span className="text-faint">({step.row_count} rows)</span>}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-col gap-3 px-3.5 py-3.5">
        {message.error ? (
          <div className="whitespace-pre-wrap font-mono text-[12.5px] leading-relaxed text-danger">
            {message.content}
            {message.streaming && <span className="animate-pulse text-brand-strong">▍</span>}
          </div>
        ) : (
          <div className="md">
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
            {message.streaming && <span className="animate-pulse text-brand-strong">▍</span>}
          </div>
        )}

        {message.redactions && message.redactions.length > 0 && (
          <div className="flex items-center gap-1.5 font-mono text-[11px] text-warning">
            <Warning size={12} />
            masked: {message.redactions.join(', ')}
          </div>
        )}

        {message.verified && (
          <div
            className={[
              'flex items-center gap-1.5 font-mono text-[11px]',
              message.verified.ok ? 'text-success' : 'text-warning',
            ].join(' ')}
          >
            {message.verified.ok ? <Check size={12} weight="bold" /> : <Warning size={12} />}
            verified{message.verified.note ? ` · ${message.verified.note}` : ''}
          </div>
        )}
      </div>

      {message.suggestions && message.suggestions.length > 0 && onSuggestion && (
        <div className="flex flex-wrap gap-2 border-t border-border px-3.5 py-3">
          {message.suggestions.map((sug) => (
            <button
              key={sug}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-chip border border-border bg-surface px-2.5 py-1 text-[12px] text-muted transition-colors duration-150 hover:border-border-strong hover:text-foreground"
              onClick={() => onSuggestion(sug)}
            >
              <ArrowRight size={12} className="text-brand-strong" />
              {sug}
            </button>
          ))}
        </div>
      )}

      {actions && <div className="flex gap-2 border-t border-border px-3.5 py-2.5">{actions}</div>}
    </article>
  );
}
