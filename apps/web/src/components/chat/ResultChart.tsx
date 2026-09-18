import { useMemo } from 'react';
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';

export interface ResultChartProps {
  columns: string[];
  rows: Record<string, unknown>[];
}

export type ChartSpec =
  | { kind: 'bar' | 'line'; category: string; series: string[] }
  | { kind: 'donut'; category: string; series: string }
  | { kind: 'scatter'; x: string; y: string }
  | { kind: 'table' };

const MAX_CATEGORIES = 12;
const DONUT_MAX_SLICES = 5;
/* Amber-anchored categorical sequence — no decorative blue/green per the design system */
const PALETTE = ['#eab308', '#a78bfa', '#f472b6', '#94a3b8', '#fb923c', '#e879f9'];

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
    return /^\d{4}-\d{2}(-\d{2})?/.test(s) || /^\d{4}\/\d{2}/.test(s)
      || /^\d{4}-\d{2}-\d{2}T/.test(s);
  });
}

/** Deterministic chart selection — no model involved. */
export function selectChart(columns: string[], rows: Record<string, unknown>[]): ChartSpec {
  if (rows.length < 2 || rows.length > 120 || columns.length < 2) return { kind: 'table' };

  const numericCols = columns.filter((c) => rows.every((r) => isNumeric(r[c]) || r[c] === null));
  const categoryCols = columns.filter((c) => !numericCols.includes(c));

  if (categoryCols.length === 0) {
    if (numericCols.length >= 2) return { kind: 'scatter', x: numericCols[0], y: numericCols[1] };
    return { kind: 'table' };
  }

  if (numericCols.length === 0) return { kind: 'table' };

  const category = categoryCols[0];
  const series = numericCols.slice(0, 3);
  const values = rows.map((r) => toNumber(r[series[0]]));

  const allNonNegative = values.every((v) => v >= 0);
  const total = values.reduce((a, b) => a + b, 0);
  if (series.length === 1 && rows.length <= DONUT_MAX_SLICES && allNonNegative && total > 0) {
    return { kind: 'donut', category, series: series[0] };
  }

  if (looksTemporal(rows.map((r) => r[category]))) {
    return { kind: 'line', category, series };
  }
  return { kind: 'bar', category, series };
}

export function shouldChart(columns: string[], rows: Record<string, unknown>[]): boolean {
  return selectChart(columns, rows).kind !== 'table';
}

function truncate(rows: Record<string, unknown>[], category: string, series: string[]): Record<string, unknown>[] {
  if (rows.length <= MAX_CATEGORIES) return rows;
  const sorted = [...rows].sort((a, b) => toNumber(b[series[0]]) - toNumber(a[series[0]]));
  const kept = sorted.slice(0, MAX_CATEGORIES - 1);
  const rest = sorted.slice(MAX_CATEGORIES - 1);
  const other: Record<string, unknown> = { [category]: 'Other' };
  for (const s of series) {
    other[s] = rest.reduce((acc, r) => acc + toNumber(r[s]), 0);
  }
  return [...kept, other];
}

export function ResultChart({ columns, rows }: ResultChartProps) {
  const spec = useMemo(() => selectChart(columns, rows), [columns, rows]);

  const data = useMemo<Record<string, unknown>[]>(() => {
    if (spec.kind === 'table' || spec.kind === 'scatter') return rows;
    const series = Array.isArray(spec.series) ? spec.series : [spec.series];
    const truncated = truncate(rows, spec.category, series);
    return truncated.map((row) => ({
      __category: String(row[spec.category] ?? ''),
      ...Object.fromEntries(series.map((c: string) => [c, toNumber(row[c])])),
    }));
  }, [rows, spec]);

  if (spec.kind === 'table') return null;

  const tip = {
    contentStyle: {
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 6, fontSize: 12, fontFamily: 'var(--font-mono)',
    },
    labelStyle: { color: 'var(--muted)' },
  };
  const axis = { stroke: 'var(--faint)', fontSize: 10, fontFamily: 'var(--font-mono)' };

  if (spec.kind === 'scatter') {
    const points = rows.map((r) => ({ x: toNumber(r[spec.x]), y: toNumber(r[spec.y]) }));
    return (
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 6, right: 10, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis type="number" dataKey="x" name={spec.x} tick={axis} />
            <YAxis type="number" dataKey="y" name={spec.y} tick={axis} />
            <ZAxis range={[40, 40]} />
            <Tooltip {...tip} cursor={{ strokeDasharray: '3 3' }} />
            <Scatter data={points} fill={PALETTE[0]} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (spec.kind === 'donut') {
    const slices = data.map((d, i) => ({
      name: String(d.__category),
      value: toNumber(d[spec.series]),
      fill: PALETTE[i % PALETTE.length],
    }));
    return (
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip {...tip} />
            <Pie data={slices} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" paddingAngle={2}>
              {slices.map((s) => (
                <Cell key={s.name} fill={s.fill} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (spec.kind === 'line') {
    return (
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 10, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="__category" tick={axis} />
            <YAxis tick={axis} />
            <Tooltip {...tip} />
            {spec.series.map((c, i) => (
              <Line key={c} type="monotone" dataKey={c} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return (
    <div className="mt-2 h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 10, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="__category" tick={axis} />
          <YAxis tick={axis} />
          <Tooltip {...tip} cursor={{ fill: 'var(--surface-2)' }} />
          {spec.series.map((c, i) => (
            <Bar key={c} dataKey={c} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]} maxBarSize={42} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
