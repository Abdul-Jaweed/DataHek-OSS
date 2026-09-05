import { useEffect, useState } from 'react';
import { Database, Plus, Trash } from '@phosphor-icons/react';
import { api } from '../api/client';
import type { Connection, ConnectionCreate } from '../api/types';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTrigger } from '../components/ui/dialog';
import { Input, Label } from '../components/ui/input';

const PROVIDERS = ['clickhouse', 'postgres', 'mysql', 'sqlite'];

export function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [provider, setProvider] = useState('clickhouse');
  const [host, setHost] = useState('');
  const [port, setPort] = useState('');
  const [database, setDatabase] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [sslmode, setSslmode] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const refresh = () => {
    setLoading(true);
    api.listConnections()
      .then(setConnections)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.createConnection(formSpec());
      setOpen(false);
      setName(''); setHost(''); setPort(''); setDatabase(''); setUsername(''); setPassword(''); setSslmode('');
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const formSpec = (): ConnectionCreate => {
    const settings: Record<string, string> = {};
    if (username) settings.username = username;
    if (password) settings.password = password;
    if (sslmode) settings.sslmode = sslmode;
    return {
      name,
      provider,
      host: host || undefined,
      port: port ? Number(port) : undefined,
      database: database || undefined,
      settings,
    };
  };

  const test = async () => {
    if (!name) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testConnection(formSpec());
      setTestResult(r.ok ? `OK · ${r.latency_ms ?? '?'}ms` : `Failed: ${r.error ?? 'unknown'}`);
    } catch (e) {
      setTestResult(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTesting(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deleteConnection(id);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-5xl p-6 sm:p-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Connections</h1>
          <p className="text-sm text-muted">
            {connections.length}/5 used · guarded by read-only enforcement
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button icon={<Plus size={16} />}>Add connection</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader title="Add connection" description="Credentials are stored as secret references." />
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="nc-name">Name</Label>
                <Input id="nc-name" className="font-mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="ch1" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="nc-provider">Provider</Label>
                <select
                  id="nc-provider"
                  className="h-9 w-full cursor-pointer rounded-md border border-border bg-surface px-3 text-sm text-foreground focus:outline-none focus:border-brand"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                >
                  {PROVIDERS.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-[1fr_110px] gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="nc-host">Host</Label>
                  <Input id="nc-host" className="font-mono" value={host} onChange={(e) => setHost(e.target.value)} placeholder="localhost" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="nc-port">Port</Label>
                  <Input id="nc-port" type="number" min={1} max={65535} className="font-mono" value={port} onChange={(e) => setPort(e.target.value)} placeholder="5432" />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="nc-db">Database</Label>
                <Input id="nc-db" className="font-mono" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="default" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="nc-user">Username</Label>
                <Input id="nc-user" className="font-mono" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="postgres" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="nc-pass">Password</Label>
                <Input id="nc-pass" type="password" className="font-mono" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="nc-ssl">SSL mode</Label>
                <select
                  id="nc-ssl"
                  className="h-9 w-full cursor-pointer rounded-md border border-border bg-surface px-3 text-sm text-foreground focus:outline-none focus:border-brand"
                  value={sslmode}
                  onChange={(e) => setSslmode(e.target.value)}
                >
                  <option value="">default</option>
                  <option value="prefer">prefer</option>
                  <option value="require">require</option>
                  <option value="verify-full">verify-full</option>
                  <option value="disable">disable</option>
                </select>
              </div>
              {testResult && (
                <p className="rounded-md border border-brand bg-surface-2 px-3 py-2 font-mono text-xs text-muted">{testResult}</p>
              )}
            </div>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="ghost">Cancel</Button>
              </DialogClose>
              <Button variant="secondary" onClick={test} loading={testing}>Test</Button>
              <Button onClick={save} loading={saving} disabled={!name}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {error && <div className="mb-4 rounded-md border border-danger bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {!loading && connections.length === 0 && (
        <EmptyState
          title="No connections yet"
          description="Add your first data source — ClickHouse, PostgreSQL, MySQL, or SQLite."
          actionLabel="Add connection"
          onAction={() => setOpen(true)}
        />
      )}

      <div className="grid gap-3">
        {connections.map((c) => (
          <Card key={c.id} className="flex items-center gap-4 p-4">
            <div className="rounded-md bg-surface-2 p-2 text-brand-strong">
              <Database size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-foreground">{c.name}</span>
                <Badge variant="brand">{c.provider}</Badge>
              </div>
              <p className="mt-0.5 truncate font-mono text-xs text-muted">
                {c.host ?? '?'}:{c.port ?? '?'}/{c.database ?? '?'}
              </p>
            </div>
            <Button variant="ghost" size="icon" aria-label={`Delete ${c.name}`} icon={<Trash size={16} />} onClick={() => {
              if (window.confirm(`Delete connection '${c.name}'?`)) void remove(c.id);
            }} />
          </Card>
        ))}
      </div>
    </div>
  );
}