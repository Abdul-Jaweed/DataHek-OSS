import { useMemo } from 'react';
import {
  Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

export interface ResultChartProps {
  columns: string[];
  rows: Record<string, unknown>[];
}

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

function looksTemporal(values: unknown[]): boolean {
  return values.length > 0 && values.every((v) => {
    const s = String(v);
    return /^\d{4}-\d{2}(-\d{2})?/.test(s) || /^\d{4}\/\d{2}/.test(s);
  });
}

export function shouldChart(columns: string[], rows: Record<string, unknown>[]): boolean {
  if (rows.length < 2 || rows.length > 60 || columns.length < 2) return false;
  const numericCols = columns.filter((c) => rows.every((r) => isNumeric(r[c]) || r[c] === null));
  const categoryCols = columns.filter((c) => !numericCols.includes(c));
  return numericCols.length >= 1 && categoryCols.length >= 1;
}

export function ResultChart({ columns, rows }: ResultChartProps) {
  const { category, values, temporal, xDomain } = useMemo(() => {
    const numericCols = columns.filter((c) => rows.every((r) => isNumeric(r[c]) || r[c] === null));
    const categoryCol = columns.find((c) => !numericCols.includes(c)) ?? columns[0];
    const valueCols = numericCols.slice(0, 2);
    const domain: [number, number] = [0, 'auto' as unknown as number];
    return {
      category: categoryCol,
      values: valueCols,
      temporal: looksTemporal(rows.map((r) => r[categoryCol])),
      xDomain: domain,
    };
  }, [columns, rows]);

  const tip = {
    contentStyle: {
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 8, fontSize: 12, fontFamily: 'var(--font-mono)',
    },
    labelStyle: { color: 'var(--muted)' },
  };

  const axis = {
    stroke: 'var(--faint)',
    fontSize: 10,
    fontFamily: 'var(--font-mono)',
  };

  return (
    <div className="mt-2 h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {temporal ? (
          <LineChart data={rows.map((r) => Object.fromEntries([
            ['__category', String(r[category] ?? '')],
            ...values.map((c) => [c, toNumber(r[c])]),
          ]))} margin={{ top: 6, right: 10, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="__category" tick={axis} />
            <YAxis tick={axis} domain={xDomain} />
            <Tooltip {...tip} />
            {values.map((c, i) => (
              <Line key={c} type="monotone" dataKey={c} stroke={i === 0 ? '#eab308' : '#38bdf8'} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
        ) : (
          <BarChart data={rows.map((r) => Object.fromEntries([
            ['__category', String(r[category] ?? '')],
            ...values.map((c) => [c, toNumber(r[c])]),
          ]))} margin={{ top: 6, right: 10, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="__category" tick={axis} />
            <YAxis tick={axis} />
            <Tooltip {...tip} cursor={{ fill: 'var(--surface-2)' }} />
            {values.map((c, i) => (
              <Bar key={c} dataKey={c} fill={i === 0 ? '#eab308' : '#38bdf8'} radius={[3, 3, 0, 0]} maxBarSize={42} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
