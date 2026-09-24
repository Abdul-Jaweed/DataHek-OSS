import { useCallback, useEffect, useState } from 'react';
import { api, contextApi, type ContextPreview, type ContextRecord, type PendingItem } from '../api/client';
import type { Connection } from '../api/types';
import { toast } from '../lib/toast';
import { Button } from '../components/ui/button';
import { Card, CardHeader, CardTitle } from '../components/ui/card';

function StateBadge({ value }: { value: string }) {
  const tone =
    value === 'active' || value === 'sufficient' || value === 'fresh'
      ? 'text-emerald-500 border-emerald-500/40'
      : value === 'failed' || value === 'insufficient'
        ? 'text-red-500 border-red-500/40'
        : 'text-amber-500 border-amber-500/40';
  return <span className={`rounded-sm border px-2 py-0.5 font-mono text-[11px] ${tone}`}>{value}</span>;
}

export function ContextPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectionId, setConnectionId] = useState('');
  const [scope, setScope] = useState('connection');
  const [record, setRecord] = useState<ContextRecord | null>(null);
  const [pending, setPending] = useState<PendingItem[]>([]);
  const [preview, setPreview] = useState<ContextPreview | null>(null);
  const [question, setQuestion] = useState('How many rows are in the table?');
  const [busy, setBusy] = useState('');
  const [jobs, setJobs] = useState<{ id: string; connection_id: string; state: string; version: number | null; error: string }[]>([]);

  const loadStatus = useCallback(async (id: string, scopeValue: string) => {
    if (!id) return;
    try {
      const [status, items] = await Promise.all([
        contextApi.status(id, scopeValue),
        contextApi.pending(id, scopeValue).catch(() => ({ items: [] as PendingItem[] })),
      ]);
      setRecord(status.context);
      setPending(items.items);
    } catch (error) {
      toast(error instanceof Error ? error.message : 'Failed to load context', 'error');
    }
  }, []);

  useEffect(() => {
    api.listConnections().then((rows) => {
      setConnections(rows);
      if (rows.length && !connectionId) setConnectionId(rows[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    loadStatus(connectionId, scope);
  }, [connectionId, scope, loadStatus]);

  const run = async (label: string, action: () => Promise<void>) => {
    setBusy(label);
    try {
      await action();
    } catch (error) {
      toast(error instanceof Error ? error.message : `${label} failed`, 'error');
    } finally {
      setBusy('');
    }
  };

  const build = () =>
    run('build', async () => {
      const result = await contextApi.build(connectionId);
      toast(`Build ${result.state}${result.version ? ` v${result.version}` : ''}${result.degraded ? ' (degraded)' : ''}`);
      await loadStatus(connectionId, scope);
    });

  const rebuild = () =>
    run('rebuild', async () => {
      const job = await contextApi.rebuild(connectionId);
      toast(`Rebuild queued (${job.id.slice(0, 12)}…)`);
      const status = await contextApi.rebuilds();
      setJobs(status.jobs);
    });

  const runPreview = () =>
    run('preview', async () => {
      setPreview(await contextApi.preview(connectionId, question));
    });

  const decide = (item: PendingItem, action: 'approve' | 'reject', patch?: Record<string, unknown>) =>
    run(`decide-${item.index}`, async () => {
      await contextApi.validate(connectionId, [
        { kind: item.kind, index: item.index, action, section: item.section, patch },
      ]);
      toast(`${action === 'approve' ? 'Approved' : 'Rejected'} ${item.label}`);
      await loadStatus(connectionId, scope);
    });

  const editGrain = (item: PendingItem) => {
    const statement = window.prompt('Grain statement', item.label);
    if (statement && statement !== item.label) {
      decide(item, 'approve', { statement });
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Context Layer</h1>
          <p className="text-sm text-muted">
            Persistent, versioned, human-validated context for the SQL planner.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="h-8 rounded-sm border border-border bg-surface-2 px-2 text-sm"
            value={connectionId}
            onChange={(event) => setConnectionId(event.target.value)}
          >
            {connections.map((connection) => (
              <option key={connection.id} value={connection.id}>
                {connection.name}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-sm border border-border bg-surface-2 px-2 text-sm"
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            <option value="connection">connection scope</option>
            <option value="schema">schema scope</option>
          </select>
          <Button size="sm" onClick={build} disabled={!connectionId || busy === 'build'}>
            {busy === 'build' ? 'Building…' : 'Build context'}
          </Button>
          <Button size="sm" variant="outline" onClick={rebuild} disabled={!connectionId || busy === 'rebuild'}>
            Queue rebuild
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Active context</CardTitle>
        </CardHeader>
        <div className="px-4 pb-4">
          {record ? (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="font-mono text-xs text-muted">{record.context_id.slice(0, 18)}…</span>
                <span>v{record.version}</span>
                <StateBadge value={record.state} />
                <StateBadge value={record.quality.state} />
                <StateBadge value={record.freshness.state} />
                <span className="text-muted">human validation {Math.round(record.quality.human_validation * 100)}%</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {record.artifact_kinds.map((kind) => (
                  <span key={kind} className="rounded-sm border border-border px-2 py-0.5 font-mono text-[11px] text-muted">
                    {kind}
                  </span>
                ))}
              </div>
              <p className="text-xs text-muted">schema hash {record.schema_hash.slice(0, 16)}…</p>
            </div>
          ) : (
            <p className="text-sm text-muted">No active context for this connection and scope.</p>
          )}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Preview for a question</CardTitle>
          </CardHeader>
          <div className="px-4 pb-4">
            <div className="flex gap-2">
              <input
                className="h-8 flex-1 rounded-sm border border-border bg-surface-2 px-2 text-sm"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
              />
              <Button size="sm" onClick={runPreview} disabled={!question.trim() || busy === 'preview'}>
                Preview
              </Button>
            </div>
            {preview && (
              <div className="mt-3 flex flex-col gap-2 text-sm">
                <div className="flex flex-wrap gap-3">
                  <span>{preview.tokens} tokens</span>
                  <StateBadge value={preview.trust} />
                  <StateBadge value={preview.quality} />
                  {preview.stale && <StateBadge value="stale" />}
                  {preview.insufficient && <StateBadge value={preview.insufficient} />}
                </div>
                <p className="text-muted">
                  tables: {preview.tables.map((table) => `${table.name} (${table.columns})`).join(', ') || '—'}
                </p>
                {preview.dropped.length > 0 && (
                  <p className="text-amber-500">dropped: {preview.dropped.join(', ')}</p>
                )}
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Rebuild queue</CardTitle>
          </CardHeader>
          <div className="px-4 pb-4">
            {jobs.length === 0 ? (
              <p className="text-sm text-muted">No rebuild jobs in this session.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-1">job</th>
                    <th className="py-1">connection</th>
                    <th className="py-1">state</th>
                    <th className="py-1">version</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id} className="border-t border-border">
                      <td className="py-1 font-mono text-xs">{job.id.slice(0, 12)}…</td>
                      <td className="py-1 font-mono text-xs">{job.connection_id.slice(0, 12)}…</td>
                      <td className="py-1"><StateBadge value={job.state} /></td>
                      <td className="py-1">{job.version ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Review inbox · {pending.length} pending</CardTitle>
        </CardHeader>
        <div className="px-4 pb-4">
          {pending.length === 0 ? (
            <p className="text-sm text-muted">Nothing awaiting review.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border">
              {pending.map((item) => (
                <li key={`${item.kind}-${item.section}-${item.index}`} className="flex flex-wrap items-center gap-3 py-2">
                  <span className="rounded-sm border border-border px-2 py-0.5 font-mono text-[11px] text-muted">
                    {item.kind}:{item.section}:{item.index}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm" title={item.label}>{item.label}</span>
                  <span className="font-mono text-[11px] text-muted">{item.provenance} · {item.confidence.toFixed(2)}</span>
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => decide(item, 'approve')}>Approve</Button>
                    {item.kind === 'granularity' && (
                      <Button size="sm" variant="outline" onClick={() => editGrain(item)}>Edit</Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => decide(item, 'reject')}>Reject</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
