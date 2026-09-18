import { useEffect, useState } from 'react';
import { FileText, Plus, Trash } from '@phosphor-icons/react';
import { api } from '../api/client';
import type { Prompt } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTrigger } from '../components/ui/dialog';
import { Input, Label, Textarea } from '../components/ui/input';

export function PromptsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [name, setName] = useState('');
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    api.listPrompts().then(setPrompts).catch(() => setPrompts([]));
  };

  useEffect(refresh, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createPrompt(name, content);
      setOpen(false);
      setName(''); setContent('');
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm('Delete this prompt?')) return;
    try {
      await api.deletePrompt(id);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-5xl p-6 sm:p-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-[21px] font-extrabold tracking-[-0.02em] text-foreground">Prompts</h1>
          <p className="text-sm text-muted">{prompts.length}/3 used · injected as planner guidance</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button icon={<Plus size={16} />} disabled={prompts.length >= 3}>New prompt</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader title="New prompt" description="Up to 3 templates. Content is injected into the planner as 'Additional guidance'." />
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="np-name">Name</Label>
                <Input id="np-name" className="font-mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="finance" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="np-content">Content</Label>
                <Textarea id="np-content" className="min-h-32 font-mono" value={content} onChange={(e) => setContent(e.target.value)} placeholder="Always aggregate revenue by region." />
                <p className="text-right font-mono text-[11px] text-faint">{content.length}/4000</p>
              </div>
              {error && <p className="text-sm text-danger">{error}</p>}
            </div>
            <DialogFooter>
              <DialogClose asChild><Button variant="ghost">Cancel</Button></DialogClose>
              <Button onClick={save} loading={saving} disabled={!name || !content}>Save</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {error && <div className="mb-4 rounded-md border border-danger bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}

      {prompts.length === 0 && (
        <EmptyState
          title="No prompts yet"
          description="Custom prompt templates give the planner domain guidance (max 3)."
          actionLabel="New prompt"
          onAction={() => setOpen(true)}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {prompts.map((p) => (
          <Card key={p.id} className="flex flex-col">
            <CardHeader>
              <div className="flex items-center gap-2">
                <FileText size={18} className="text-brand-strong" />
                <CardTitle className="font-mono text-sm">{p.name}</CardTitle>
              </div>
              <Button variant="ghost" size="icon" aria-label={`Delete ${p.name}`} icon={<Trash size={16} />} onClick={() => remove(p.id)} />
            </CardHeader>
            <CardDescription className="line-clamp-3 font-mono text-xs">{p.content}</CardDescription>
          </Card>
        ))}
      </div>
    </div>
  );
}