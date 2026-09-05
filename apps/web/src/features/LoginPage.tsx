import { Lightning, LockKey } from '@phosphor-icons/react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Input, Label } from '../components/ui/input';
import { useStore } from '../store/use-store';

export function LoginPage() {
  const navigate = useNavigate();
  const { saveApiKey } = useStore();
  const [username, setUsername] = useState('datahek');
  const [password, setPassword] = useState('datahek');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.login(username.trim(), password);
      saveApiKey(res.token);
      navigate('/chat', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm p-8">
        <div className="mb-6 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand text-brand-contrast">
            <Lightning size={20} weight="fill" />
          </span>
          <span className="text-lg font-bold text-foreground">
            Data<span className="text-brand-strong">Hek</span>
          </span>
          <span className="ml-auto rounded border border-border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest text-faint">
            OSS
          </span>
        </div>

        <h1 className="text-xl font-semibold text-foreground">Sign in</h1>
        <p className="mt-1 text-sm text-muted">Local credentials for this DataHek instance.</p>

        <form className="mt-6 space-y-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="lg-user">Username</Label>
            <Input id="lg-user" className="font-mono" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="lg-pass">Password</Label>
            <Input id="lg-pass" type="password" className="font-mono" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </div>

          {error && (
            <p className="rounded-md border border-danger bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </p>
          )}

          <Button type="submit" className="w-full" loading={submitting}>
            <LockKey size={16} /> Sign in
          </Button>
        </form>

        <p className="mt-5 text-center font-mono text-[11px] text-faint">
          default · datahek / datahek
        </p>
      </Card>
    </div>
  );
}