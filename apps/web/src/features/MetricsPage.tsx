import { useEffect, useState } from 'react';
import { Plus, Ruler, Trash } from '@phosphor-icons/react';
import { api } from '../api/client';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { EmptyState } from '../components/ui/empty-state';
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTrigger } from '../components/ui/dialog';
import { Input, Label } from '../components/ui/input';

interface Metric {
  id: string;
  name: string;
  table: string;
  aggregate: string;
  column: string;
  filter: string | null;
  description: string;
}

const AGGREGATES = ['count', 'count_distinct', 'sum', 'avg', 'min', 'max', 'uniq'];

export function MetricsPage() {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState('');
  const [table, setTable] = useState('');
  const [aggregate, setAggregate] = useState('sum');
  const [column, setColumn] = useState('*');
  const [filter, setFilter] = useState('');
  const [description, setDescription] = useState('');

  const refresh = () => {
    api
      .listMetrics()
      .then(setMetrics)
      .catch(() => setMetrics([]))
      .finally(() => setLoaded(true));
  };

  useEffect(refresh, []);

  const reset = () => {
    setName(''); setTable(''); setAggregate('sum'); setColumn('*'); setFilter(''); setDescription('');
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createMetric({
        name, table, aggregate, column: column || '*',
        filter: filter || null, description,
      });
      setOpen(false);
      reset();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm('Delete this metric?')) return;
    try {
      await api.deleteMetric(id);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-4xl p-6 sm:p-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-[21px] font-extrabold tracking-[-0.02em] text-foreground">Semantic layer</h1>
          <p className="text-sm text-muted">
            Named metric definitions the planner prefers over guessing — e.g. revenue = sum(amount) on orders
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button icon={<Plus size={16} />} onClick={reset}>New metric</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader
              title="New metric"
              description="The planner receives these definitions on every question and prefers them when relevant."
            />
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="m-name">Name</Label>
                  <Input id="m-name" className="font-mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="revenue" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="m-table">Table</Label>
                  <Input id="m-table" className="font-mono" value={table} onChange={(e) => setTable(e.target.value)} placeholder="orders" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="m-agg">Aggregate</Label>
                  <select
                    id="m-agg"
                    className="h-9 w-full cursor-pointer rounded-md border border-border bg-surface-2 px-3 font-mono text-sm text-foreground focus:border-border-strong"
                    value={aggregate}
                    onChange={(e) => setAggregate(e.target.value)}
                  >
                    {AGGREGATES.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="m-col">Column</Label>
                  <Input id="m-col" className="font-mono" value={column} onChange={(e) => setColumn(e.target.value)} placeholder="amount or *" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="m-filter">Filter (optional SQL predicate)</Label>
                <Input id="m-filter" className="font-mono" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="status = 'paid'" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="m-desc">Description (aliases in plain words)</Label>
                <Input id="m-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="total sales, gross revenue" />
              </div>
              {error && <p className="text-sm text-danger">{error}</p>}
            </div>
            <DialogFooter>
              <DialogClose asChild><Button variant="ghost">Cancel</Button></DialogClose>
              <Button onClick={save} loading={saving} disabled={!name || !table}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {error && <div className="mb-4 rounded-md border border-danger bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loaded && metrics.length === 0 && (
        <EmptyState
          title="No metrics defined"
          description="Define metrics once — the planner uses them for every user, so 'revenue' always means the same thing."
          actionLabel="New metric"
          onAction={() => setOpen(true)}
          icon={<Ruler size={40} weight="thin" />}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {metrics.map((m) => (
          <Card key={m.id} className="flex items-start gap-3 p-4">
            <div className="rounded-md bg-surface-2 p-2 text-brand-strong">
              <Ruler size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-semibold text-foreground">{m.name}</span>
                <Badge variant="brand">{m.aggregate}</Badge>
              </div>
              <p className="mt-1 break-all font-mono text-xs text-muted">
                {m.aggregate}({m.column}) on {m.table}
                {m.filter ? ` where ${m.filter}` : ''}
              </p>
              {m.description && <p className="mt-1 text-xs text-faint">{m.description}</p>}
            </div>
            <Button variant="ghost" size="icon" aria-label={`Delete ${m.name}`} icon={<Trash size={16} />} onClick={() => remove(m.id)} />
          </Card>
        ))}
      </div>
    </div>
  );
}
