import {
  ChatCircleText,
  Database,
  Lightning,
  LockSimple,
  MagnifyingGlass,
  ShieldCheck,
  Speedometer,
} from '@phosphor-icons/react';
import { Link } from 'react-router-dom';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';

const FEATURES = [
  {
    icon: <ChatCircleText size={22} />,
    title: 'Natural-language data',
    text: 'Ask questions in plain English. The planner builds validated, read-only queries against your schema.',
  },
  {
    icon: <Database size={22} />,
    title: 'Four connectors',
    text: 'ClickHouse, PostgreSQL, MySQL and SQLite — one engine, one interface, real SQL under the hood.',
  },
  {
    icon: <ShieldCheck size={22} />,
    title: 'Safe by construction',
    text: 'SQL AST validation, multi-statement rejection, injection detection and structural read-only enforcement.',
  },
  {
    icon: <LockSimple size={22} />,
    title: 'Audited by default',
    text: 'Every plan, execution and refusal lands in a structured audit trail you can replay.',
  },
  {
    icon: <Speedometer size={22} />,
    title: 'Streaming answers',
    text: 'Tokens stream to your screen while rows arrive as tables — no waiting for full completion.',
  },
  {
    icon: <MagnifyingGlass size={22} />,
    title: 'Evaluated regressions',
    text: 'A curated dataset scores plan validity, safety, execution and latency on every run.',
  },
];

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      <header className="flex h-16 items-center gap-2 border-b border-border px-6">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand text-brand-contrast">
          <Lightning size={20} weight="fill" />
        </span>
        <span className="text-lg font-bold text-foreground">
          Data<span className="text-brand-strong">Hek</span>
        </span>
        <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-widest text-faint">
          OSS
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Link to="/login">
            <Button variant="ghost">Sign in</Button>
          </Link>
          <Link to="/chat">
            <Button>Launch app</Button>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6">
        <section className="pb-16 pt-20 text-center sm:pt-28">
          <Badge variant="brand" className="mb-6">
            <Lightning size={12} /> agentic data platform
          </Badge>
          <h1 className="mx-auto max-w-2xl text-4xl font-bold leading-tight tracking-tight text-foreground sm:text-5xl">
            Ask your data anything.
            <span className="block text-brand-strong">Get answers in seconds.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-base text-muted">
            DataHek turns natural language into validated, read-only SQL — with guardrails, audit
            and evaluation built into the engine.
          </p>
          <div className="mt-8 flex items-center justify-center gap-3">
            <Link to="/login">
              <Button size="lg">Start asking</Button>
            </Link>
            <Link to="/chat">
              <Button size="lg" variant="secondary">
                Open the app
              </Button>
            </Link>
          </div>
        </section>

        <section className="grid gap-4 pb-24 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <Card key={f.title} className="p-6">
              <div className="mb-4 grid h-10 w-10 place-items-center rounded-lg bg-brand-soft text-brand-strong">
                {f.icon}
              </div>
              <h3 className="text-base font-semibold text-foreground">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{f.text}</p>
            </Card>
          ))}
        </section>
      </main>

      <footer className="border-t border-border py-8 text-center font-mono text-xs text-faint">
        DataHek OSS v0.2.0 · Apache-2.0 · self-hosted
      </footer>
    </div>
  );
}