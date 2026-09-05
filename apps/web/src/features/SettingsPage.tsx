import { useEffect, useState } from 'react';
import { Key, Lightning, Lock, Wrench } from '@phosphor-icons/react';
import { api } from '../api/client';
import type { Health } from '../api/types';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Input, Label } from '../components/ui/input';
import { useStore } from '../store/use-store';

interface LlmSettings {
  base_url: string;
  model: string;
  api_key_set: boolean;
}

export function SettingsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [keyDraft, setKeyDraft] = useState('');
  const { apiKey, saveApiKey, removeApiKey } = useStore();

  const [llm, setLlm] = useState<LlmSettings | null>(null);
  const [llmBaseUrl, setLlmBaseUrl] = useState('');
  const [llmKey, setLlmKey] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmSaving, setLlmSaving] = useState(false);
  const [llmMsg, setLlmMsg] = useState<string | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api
      .getLlmSettings()
      .then((s) => {
        setLlm(s);
        setLlmBaseUrl(s.base_url);
        setLlmModel(s.model);
      })
      .catch(() => setLlm(null));
  }, []);

  const saveLlm = async () => {
    setLlmSaving(true);
    setLlmMsg(null);
    try {
      const body: { base_url?: string; api_key?: string; model?: string } = {};
      if (llmBaseUrl) body.base_url = llmBaseUrl;
      if (llmKey) body.api_key = llmKey;
      if (llmModel) body.model = llmModel;
      const saved = await api.saveLlmSettings(body);
      setLlm(saved);
      setLlmKey('');
      setLlmMsg(`Saved — model ${saved.model} · ${saved.base_url}`);
    } catch (e) {
      setLlmMsg(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLlmSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6 sm:p-10">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
        <p className="text-sm text-muted">LLM provider, authentication, and environment</p>
      </div>

      <Card>
        <div className="mb-4 flex items-center gap-2">
          <Lightning size={18} className="text-brand-strong" />
          <h3 className="text-base font-semibold text-foreground">LLM provider</h3>
          {llm && <Badge variant="brand">{llm.model}</Badge>}
        </div>
        <p className="mb-4 text-sm text-muted">
          Point the engine at any OpenAI-compatible endpoint. Leave a field empty to keep its current value.
        </p>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="llm-url">Base URL</Label>
            <Input id="llm-url" className="font-mono" value={llmBaseUrl} onChange={(e) => setLlmBaseUrl(e.target.value)} placeholder="https://…/v1" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="llm-key">API key</Label>
            <Input id="llm-key" type="password" className="font-mono" value={llmKey} onChange={(e) => setLlmKey(e.target.value)} placeholder={llm?.api_key_set ? '•••••••• (saved)' : 'sk-…'} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="llm-model">Model</Label>
            <Input id="llm-model" className="font-mono" value={llmModel} onChange={(e) => setLlmModel(e.target.value)} placeholder="model-id" />
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={saveLlm} loading={llmSaving}>Save LLM settings</Button>
            {llmMsg && <p className="text-xs text-muted">{llmMsg}</p>}
          </div>
        </div>
        {health && (
          <dl className="mt-6 space-y-2 border-t border-border pt-4 font-mono text-sm">
            <div className="flex justify-between"><dt className="text-muted">version</dt><dd className="text-foreground">{health.version}</dd></div>
            <div className="flex justify-between"><dt className="text-muted">providers</dt><dd className="text-foreground">{health.providers.join(', ')}</dd></div>
          </dl>
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