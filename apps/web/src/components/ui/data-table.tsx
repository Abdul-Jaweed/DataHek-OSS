import { CaretDown, CaretUp, CaretUpDown } from '@phosphor-icons/react';
import { useEffect, useMemo, useState } from 'react';
import { cn } from '../../lib/utils';

export interface DataTableProps {
  columns: string[];
  rows: Record<string, unknown>[];
  pageSize?: number;
  ariaLabel?: string;
  note?: string;
}

type SortDir = 'asc' | 'desc';

function isNumeric(value: unknown): boolean {
  if (typeof value === 'number') return true;
  if (typeof value === 'string' && value.trim() !== '') {
    return Number.isFinite(Number(value.replace(/,/g, '')));
  }
  return false;
}

function toNumber(value: unknown): number {
  if (typeof value === 'number') return value;
  return Number(String(value).replace(/,/g, ''));
}

export function DataTable({
  columns,
  rows,
  pageSize = 25,
  ariaLabel = 'Query results',
  note,
}: DataTableProps) {
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    setPage(0);
  }, [rows]);

  const numericCols = useMemo(
    () =>
      new Set(
        columns.filter((c) => rows.length > 0 && rows.every((r) => isNumeric(r[c]) || r[c] === null)),
      ),
    [columns, rows],
  );

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const { key, dir } = sort;
    const factor = dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
      if (numericCols.has(key)) return (toNumber(a[key]) - toNumber(b[key])) * factor;
      return String(a[key] ?? '').localeCompare(String(b[key] ?? '')) * factor;
    });
  }, [rows, sort, numericCols]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const start = safePage * pageSize;
  const visible = sorted.slice(start, start + pageSize);

  const toggleSort = (key: string) => {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: 'asc' };
      if (prev.dir === 'asc') return { key, dir: 'desc' };
      return null;
    });
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left" aria-label={ariaLabel}>
        <thead>
          <tr className="h-9 border-b border-border bg-surface-2">
            {columns.map((c) => {
              const active = sort?.key === c;
              return (
                <th
                  key={c}
                  aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={cn('kicker px-3.5 font-medium text-muted', numericCols.has(c) && 'text-right')}
                >
                  <button
                    className={cn(
                      'inline-flex cursor-pointer items-center gap-1 transition-colors duration-150 hover:text-foreground',
                      numericCols.has(c) && 'flex-row-reverse',
                    )}
                    onClick={() => toggleSort(c)}
                  >
                    {c}
                    {active ? (
                      sort!.dir === 'asc' ? (
                        <CaretUp size={10} weight="bold" className="text-brand-strong" />
                      ) : (
                        <CaretDown size={10} weight="bold" className="text-brand-strong" />
                      )
                    ) : (
                      <CaretUpDown size={10} className="text-faint" />
                    )}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="font-mono text-[12px]">
          {visible.map((row, i) => (
            <tr key={start + i} className="h-9 border-b border-border last:border-b-0 hover:bg-surface-2/60">
              {columns.map((c) => (
                <td
                  key={c}
                  className={cn('px-3.5 text-foreground', numericCols.has(c) && 'text-right tabular-nums')}
                >
                  {String(row[c] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-surface-2 px-3.5 py-2 font-mono text-[11px] text-muted">
        <span>
          Showing {sorted.length === 0 ? 0 : start + 1}–{Math.min(start + pageSize, sorted.length)} of{' '}
          {sorted.length} rows
          {note ? ` · ${note}` : ''}
        </span>
        {pageCount > 1 && (
          <div className="flex items-center gap-1">
            <button
              className="cursor-pointer rounded-sm border border-border bg-surface px-2 py-0.5 text-muted transition-colors duration-150 hover:text-foreground disabled:cursor-default disabled:opacity-40 disabled:hover:text-muted"
              onClick={() => setPage(safePage - 1)}
              disabled={safePage === 0}
            >
              Prev
            </button>
            <span className="px-2 py-0.5 font-bold text-foreground">
              {safePage + 1} / {pageCount}
            </span>
            <button
              className="cursor-pointer rounded-sm border border-border bg-surface px-2 py-0.5 text-muted transition-colors duration-150 hover:text-foreground disabled:cursor-default disabled:opacity-40 disabled:hover:text-muted"
              onClick={() => setPage(safePage + 1)}
              disabled={safePage >= pageCount - 1}
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
