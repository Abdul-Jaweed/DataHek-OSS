import { useEffect, useState } from 'react';
import { CheckCircle, ShieldCheck, XCircle } from '@phosphor-icons/react';
import { api } from '../api/client';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/ui/empty-state';

interface Approval {
  id: string;
  status: string;
  reason: string;
  requester: string;
  resource_ref: string;
}

export function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    api
      .listApprovals()
      .then(setApprovals)
      .catch(() => setApprovals([]))
      .finally(() => setLoaded(true));
  };

  useEffect(refresh, []);

  const decide = async (id: string, decision: 'approve' | 'reject') => {
    setBusy(id);
    setError(null);
    try {
      await api.decideApproval(id, decision);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const pending = approvals.filter((a) => a.status === 'pending');
  const decided = approvals.filter((a) => a.status !== 'pending');

  const statusBadge = (status: string) =>
    status === 'pending' ? (
      <Badge variant="warning">pending</Badge>
    ) : status === 'approved' || status === 'consumed' ? (
      <Badge variant="brand">{status}</Badge>
    ) : (
      <Badge variant="danger">{status}</Badge>
    );

  const row = (a: Approval) => (
    <Card key={a.id} className="flex flex-wrap items-center gap-3 p-4">
      <ShieldCheck size={20} className="text-warning" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {statusBadge(a.status)}
          <span className="truncate text-sm text-foreground">{a.reason}</span>
        </div>
        <p className="mt-0.5 truncate font-mono text-xs text-muted">
          {a.requester} · {a.resource_ref} · {a.id.slice(-10)}
        </p>
      </div>
      {a.status === 'pending' && (
        <div className="flex gap-2">
          <Button size="sm" loading={busy === a.id} icon={<CheckCircle size={15} />} onClick={() => decide(a.id, 'approve')}>
            Approve
          </Button>
          <Button size="sm" variant="destructive" loading={busy === a.id} icon={<XCircle size={15} />} onClick={() => decide(a.id, 'reject')}>
            Reject
          </Button>
        </div>
      )}
    </Card>
  );

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6 sm:p-10">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Approvals</h1>
        <p className="text-sm text-muted">
          Human-in-the-loop gate — large exports and sensitive tables wait here for a decision
        </p>
      </div>

      {error && <div className="rounded-md border border-danger bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {loaded && approvals.length === 0 && (
        <EmptyState
          title="No approval requests"
          description="Queries that exceed the row threshold or touch sensitive tables appear here before they execute."
        />
      )}

      {pending.length > 0 && (
        <div className="space-y-3">
          <h2 className="font-mono text-xs uppercase tracking-wider text-muted">Pending · {pending.length}</h2>
          {pending.map(row)}
        </div>
      )}

      {decided.length > 0 && (
        <div className="space-y-3">
          <h2 className="font-mono text-xs uppercase tracking-wider text-muted">History · {decided.length}</h2>
          {decided.map(row)}
        </div>
      )}
    </div>
  );
}