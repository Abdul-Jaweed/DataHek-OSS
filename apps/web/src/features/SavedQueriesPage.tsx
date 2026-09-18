import { useEffect, useState } from 'react';
import { BookmarkSimple, Clock, Plus, Play, Trash } from '@phosphor-icons/react';
import { api } from '../api/client';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { EmptyState } from '../components/ui/empty-state';
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTrigger } from '../components/ui/dialog';
import { Input, Label } from '../components/ui/input';

interface SavedQuery {
  id: string;
  name: string;
  question: string;
  connection_id: string;
}

interface Schedule {
  id: string;
  saved_query_id: string;
  interval_seconds: number;
  last_status: string | null;
  last_rows: number | null;
  next_run_at: string;
}

interface Connection {
  id: string;
  name: string;
}

export function SavedQueriesPage() {
  const [queries, setQueries] = useState<SavedQuery[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState('');
  const [question, setQuestion] = useState('');
  const [connectionId, setConnectionId] = useState('');

  const [running, setRunning] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, { answer: string; rows: number | null }>>({});

  const refresh = () => {
    Promise.all([api.listSavedQueries(), api.listSchedules(), api.listConnections()])
      .then(([q, s, c]) => {
        setQueries(q);
        setSchedules(s);
        setConnections(c);
        setConnectionId((prev) => prev || c[0]?.id || '');
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoaded(true));
  };

  useEffect(refresh, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createSavedQuery({ name, question, connectionId });
      setOpen(false);
      setName('');
      setQuestion('');
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm('Delete this saved query (and its schedules)?')) return;
    try {
      await api.deleteSavedQuery(id);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const run = async (q: SavedQuery) => {
    setRunning(q.id);
    setResult((r) => ({ ...r, [q.id]: { answer: 'Running…', rows: null } }));
    try {
      const r = await api.runSavedQuery(q.id);
      setResult((prev) => ({ ...prev, [q.id]: { answer: r.answer || 'No answer', rows: r.row_count ?? null } }));
    } catch (e) {
      setResult((prev) => ({ ...prev, [q.id]: { answer: e instanceof Error ? e.message : String(e), rows: null } }));
    } finally {
      setRunning(null);
    }
  };

  const scheduleEvery = async (q: SavedQuery, minutes: string) => {
    const parsed = Number(minutes);
    if (!parsed || parsed <= 0) return;
    try {
      await api.createSchedule(q.id, Math.round(parsed * 60));
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const removeSchedule = async (id: string) => {
    try {
      await api.deleteSchedule(id);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const connectionName = (id: string) => connections.find((c) => c.id === id)?.name ?? id.slice(-8);

  return (
    <div className="mx-auto max-w-4xl p-6 sm:p-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Saved queries</h1>
          <p className="text-sm text-muted">Reusable questions with optional schedules — every run goes through the full guarded pipeline</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button icon={<Plus size={16} />}>Save a query</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader title="Save a query" description="Give a question a name so you can run it again or schedule it." />
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="sq-name">Name</Label>
                <Input id="sq-name" className="font-mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="weekly errors" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sq-q">Question</Label>
                <Input id="sq-q" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="How many errors per service this week?" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sq-c">Connection</Label>
                <select
                  id="sq-c"
                  className="h-9 w-full cursor-pointer rounded-md border border-border bg-surface px-3 font-mono text-sm text-foreground focus:outline-none focus:border-brand"
                  value={connectionId}
                  onChange={(e) => setConnectionId(e.target.value)}
                >
                  {connections.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <DialogFooter>
              <DialogClose asChild><Button variant="ghost">Cancel</Button></DialogClose>
              <Button onClick={save} loading={saving} disabled={!name || !question || !connectionId}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {error && <div className="mb-4 rounded-md border border-danger bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loaded && queries.length === 0 && (
        <EmptyState
          title="No saved queries"
          description="Save a question once, then run it any time — or schedule it to run automatically."
          actionLabel="Save a query"
          onAction={() => setOpen(true)}
          icon={<BookmarkSimple size={40} weight="thin" />}
        />
      )}

      <div className="space-y-3">
        {queries.map((q) => {
          const qSchedules = schedules.filter((s) => s.saved_query_id === q.id);
          const r = result[q.id];
          return (
            <Card key={q.id} className="p-4">
              <div className="flex items-center gap-3">
                <div className="rounded-md bg-surface-2 p-2 text-brand-strong">
                  <BookmarkSimple size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-foreground">{q.name}</span>
                    <Badge variant="neutral">{connectionName(q.connection_id)}</Badge>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted">{q.question}</p>
                </div>
                <Button size="sm" loading={running === q.id} icon={<Play size={14} />} onClick={() => run(q)}>Run</Button>
                <Button variant="ghost" size="icon" aria-label={`Delete ${q.name}`} icon={<Trash size={16} />} onClick={() => remove(q.id)} />
              </div>

              {r && (
                <div className={`mt-3 rounded-md border px-3 py-2 text-sm ${r.rows === null && !r.answer.includes('Running') ? 'border-danger bg-danger-soft text-danger' : 'border-border bg-surface-2 text-foreground'}`}>
                  {r.answer}
                  {r.rows !== null && <span className="ml-2 font-mono text-xs text-muted">({r.rows} rows)</span>}
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
                <Clock size={14} className="text-muted" />
                {qSchedules.map((s) => (
                  <span key={s.id} className="flex items-center gap-2 rounded-md border border-border px-2 py-1 font-mono text-[11px] text-muted">
                    every {Math.round(s.interval_seconds / 60) || 1}m
                    {s.last_status && (
                      <Badge variant={s.last_status === 'ok' ? 'brand' : s.last_status === 'error' ? 'danger' : 'neutral'}>
                        {s.last_status}{s.last_rows !== null ? ` · ${s.last_rows}r` : ''}
                      </Badge>
                    )}
                    <button className="cursor-pointer text-faint hover:text-danger" onClick={() => removeSchedule(s.id)} aria-label="Remove schedule">×</button>
                  </span>
                ))}
                <form
                  className="ml-auto flex items-center gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const input = (e.target as HTMLFormElement).elements.namedItem('minutes') as HTMLInputElement;
                    void scheduleEvery(q, input.value);
                    input.value = '';
                  }}
                >
                  <input
                    name="minutes"
                    type="number"
                    min={1}
                    placeholder="min"
                    className="h-7 w-16 rounded-md border border-border bg-surface px-2 font-mono text-xs text-foreground focus:outline-none focus:border-brand"
                    aria-label="Schedule interval in minutes"
                  />
                  <Button size="sm" variant="secondary" type="submit">Schedule</Button>
                </form>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}