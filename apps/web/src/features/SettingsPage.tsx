import { useEffect, useState } from 'react';
import { Key, Lightning, Lock, Wrench } from '@phosphor-icons/react';
import { api } from '../api/client';
import type { Health } from '../api/types';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { useStore } from '../store/use-store';

export function SettingsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [keyDraft, setKeyDraft] = useState('');
  const { apiKey, saveApiKey, removeApiKey } = useStore();

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6 sm:p-10">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
        <p className="text-sm text-muted">Environment visibility — configuration is env-driven</p>
      </div>

      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Lightning size={18} className="text-brand-strong" />
          <h3 className="text-base font-semibold text-foreground">LLM provider</h3>
        </div>
        {health ? (
          <dl className="space-y-2 font-mono text-sm">
            <div className="flex justify-between"><dt className="text-muted">model</dt><dd className="text-foreground">{import.meta.env.VITE_LLM_MODEL ?? 'mimo-v2.5 (server default)'}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">version</dt><dd className="text-foreground">{health.version}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">providers</dt><dd className="text-foreground">{health.providers.join(', ')}</dd></div>
          </dl>
        ) : (
          <p className="text-sm text-muted">Health unavailable — is the API running?</p>
        )}
      </Card>

      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Key size={18} className="text-warning" />
          <h3 className="text-base font-semibold text-foreground">API key</h3>
          {apiKey ? <Badge variant="brand">saved</Badge> : <Badge variant="neutral">none</Badge>}
        </div>
        <p className="mb-3 text-sm text-muted">
          Required when the server runs with <code className="font-mono text-muted">DATAHEK_AUTH_MODE=local</code>. Stored in this browser only.
        </p>
        <div className="flex gap-2">
          <Input type="password" className="font-mono" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)} placeholder="X-API-Key" aria-label="API key" />
          <Button onClick={() => { if (keyDraft) { saveApiKey(keyDraft); setKeyDraft(''); } }}>Save</Button>
          {apiKey && <Button variant="ghost" onClick={removeApiKey}>Clear</Button>}
        </div>
      </Card>

      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Lock size={18} className="text-brand-strong" />
          <h3 className="text-base font-semibold text-foreground">Entitlements</h3>
        </div>
        {health && (
          <ul className="space-y-2 font-mono text-sm">
            {Object.entries(health.entitlements).map(([k, v]) => (
              <li key={k} className="flex justify-between">
                <span className="text-muted">{k}</span>
                <span className="text-foreground">{v}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Wrench size={18} className="text-muted" />
          <h3 className="text-base font-semibold text-foreground">About</h3>
        </div>
        <p className="text-sm text-muted">
          DataHek OSS v0.2.0 · universal conversational data platform · read-only by construction · Apache-2.0
        </p>
      </Card>
    </div>
  );
}