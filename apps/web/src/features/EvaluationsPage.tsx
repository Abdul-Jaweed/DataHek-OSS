import { useEffect, useState } from 'react';
import { CaretDown, CaretRight, Play } from '@phosphor-icons/react';
import { api } from '../api/client';
import type { EvaluationReport } from '../api/types';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { EmptyState } from '../components/ui/empty-state';
import { Skeleton } from '../components/ui/skeleton';

interface RunDetail {
  total: number;
  pass_rate: number;
  runs: unknown[];
}

export function EvaluationsPage() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [runs, setRuns] = useState<RunDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const refresh = () => {
    api.listEvaluations().then(setRuns).catch(() => setRuns(null));
  };

  useEffect(refresh, []);

  const run = async () => {
    setRunning(true);
    try {
      const r = await api.runEvaluations();
      setReport(r);
      refresh();
    } finally {
      setRunning(false);
    }
  };

  const rate = report?.pass_rate ?? runs?.pass_rate ?? 0;
  const total = report?.total ?? runs?.total ?? 0;
  const passed = report?.passed ?? Math.round(rate * total);

  return (
    <div className="mx-auto max-w-5xl p-6 sm:p-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-[21px] font-extrabold tracking-[-0.02em] text-foreground">Evaluations</h1>
          <p className="text-sm text-muted">Curated regression dataset · real engine</p>
        </div>
        <Button icon={<Play size={16} />} onClick={run} loading={running}>
          {running ? 'Running…' : 'Run evaluation'}
        </Button>
      </div>

      {running && (
        <div className="mb-4 grid grid-cols-3 gap-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      )}

      {!running && (report || runs) && (
        <div className="mb-6 grid grid-cols-3 gap-3">
          <Card className="text-center">
            <p className="font-mono text-3xl font-bold text-foreground">{total}</p>
            <p className="text-xs text-muted">Cases</p>
          </Card>
          <Card className="text-center">
            <p className="font-mono text-3xl font-bold text-brand-strong">{passed}</p>
            <p className="text-xs text-muted">Passed</p>
          </Card>
          <Card className="text-center">
            <p className="font-mono text-3xl font-bold text-foreground">{Math.round(rate * 100)}%</p>
            <p className="text-xs text-muted">Pass rate</p>
          </Card>
        </div>
      )}

      {report && report.cases.length > 0 && (
        <Card className="mb-6">
          <button
            className="flex w-full cursor-pointer items-center gap-2 text-left"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? <CaretDown size={16} /> : <CaretRight size={16} />}
            <span className="text-sm font-semibold text-foreground">Latest run — case scores</span>
          </button>
          {expanded && (
            <div className="mt-4 space-y-2">
              {report.cases.map((c) => (
                <div key={c.name} className="flex items-center gap-3 rounded-md bg-surface px-3 py-2">
                  <span className="font-mono text-xs text-foreground">{c.name}</span>
                  <Badge variant={c.passed ? 'brand' : 'danger'}>{c.passed ? 'PASS' : 'FAIL'}</Badge>
                  <span className="ml-auto font-mono text-[11px] text-muted">
                    {Object.entries(c.scores).map(([k, v]) => `${k}=${v.toFixed(2)}`).join(' · ')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {!running && !report && !runs && (
        <EmptyState
          title="No runs yet"
          description="Run the built-in dataset to score plan validity, safety, execution, and latency."
          actionLabel="Run evaluation"
          onAction={run}
        />
      )}
    </div>
  );
}