import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { api } from '../api/client';
import type { Connection } from '../api/types';
import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';

export function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [host, setHost] = useState('');
  const [database, setDatabase] = useState('');
  const [provider, setProvider] = useState('clickhouse');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const refresh = () => {
    setLoading(true);
    api.listConnections()
      .then(setConnections)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.createConnection({ name, provider, host: host || 'localhost', database: database || 'default' });
      setShowForm(false);
      setName(''); setHost(''); setDatabase('');
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!name) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testConnection(name);
      setTestResult(r.ok ? `OK · ${r.latency_ms ?? '?'}ms` : `Failed: ${r.error ?? 'unknown'}`);
    } catch (e) {
      setTestResult(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h1>Connections</h1>
        <Button variant="primary" icon={<Plus size={16} />} onClick={() => setShowForm(true)}>
          Add connection
        </Button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {showForm && (
        <div className="conn-form card">
          <div className="form-row">
            <label className="caption" htmlFor="cf-name">Name</label>
            <input id="cf-name" className="mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="ch1" />
          </div>
          <div className="form-row">
            <label className="caption" htmlFor="cf-provider">Provider</label>
            <select id="cf-provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="clickhouse">ClickHouse</option>
              <option value="postgres">PostgreSQL</option>
              <option value="mysql">MySQL</option>
              <option value="sqlite">SQLite (host = file path)</option>
            </select>
          </div>
          <div className="form-row">
            <label className="caption" htmlFor="cf-host">Host</label>
            <input id="cf-host" className="mono" value={host} onChange={(e) => setHost(e.target.value)} placeholder="localhost" />
          </div>
          <div className="form-row">
            <label className="caption" htmlFor="cf-db">Database</label>
            <input id="cf-db" className="mono" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="default" />
          </div>
          <div className="form-actions">
            <Button variant="secondary" onClick={test} loading={testing}>Test</Button>
            <Button variant="primary" onClick={save} loading={saving} disabled={!name}>Save</Button>
            <Button variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
          </div>
          {testResult && <div className="alert alert-info mono">{testResult}</div>}
        </div>
      )}

      {!loading && connections.length === 0 && !showForm && (
        <EmptyState
          title="No connections yet"
          description="Add your first data source — ClickHouse, PostgreSQL, MySQL, or SQLite."
          actionLabel="Add connection"
          onAction={() => setShowForm(true)}
        />
      )}

      <div className="conn-list">
        {connections.map((c) => (
          <div className="conn-row card" key={c.id}>
            <div className="mono conn-name">{c.name}</div>
            <div className="muted conn-detail">
              {c.provider} · {c.host ?? '?'}:{c.port ?? '?'}/{c.database ?? '?'}
            </div>
            <Button variant="icon" aria-label={`Delete ${c.name}`} onClick={() => {
              if (confirm(`Delete connection '${c.name}'?`)) {
                // NOTE: DELETE /connections/{id} not yet exposed by the backend UI flow
                void c;
              }
            }}>
              <Trash2 size={16} />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}