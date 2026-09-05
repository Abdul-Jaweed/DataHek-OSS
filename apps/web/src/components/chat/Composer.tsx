import { PaperPlaneRight } from '@phosphor-icons/react';
import { useState } from 'react';
import { Button } from '../ui/button';
import { Textarea } from '../ui/input';

export interface ComposerProps {
  hasConnection: boolean;
  streaming: boolean;
  onSend: (text: string) => void;
}

export function Composer({ hasConnection, streaming, onSend }: ComposerProps) {
  const [text, setText] = useState('');
  const canSend = hasConnection && text.trim().length > 0 && !streaming;

  const send = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText('');
  };

  return (
    <div className="border-t border-border bg-background/90 px-4 py-3 backdrop-blur sm:px-6">
      <div className="flex items-end gap-3">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder={hasConnection ? 'Ask your data…' : 'Select a connection first'}
          rows={2}
          className="min-h-[42px] resize-none"
          aria-label="Question"
          disabled={!hasConnection}
        />
        <Button variant="default" size="icon" onClick={send} disabled={!canSend} loading={streaming} aria-label="Send">
          {!streaming && <PaperPlaneRight size={18} />}
        </Button>
      </div>
      {!hasConnection && (
        <p className="mt-2 text-xs text-muted">Add and select a connection to start asking.</p>
      )}
    </div>
  );
}