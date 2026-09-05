import { Send } from 'lucide-react';
import { useState } from 'react';
import { Button } from '../ui/Button';

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
    <div className="composer">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        placeholder={hasConnection ? 'Ask a question…' : 'Select a connection first'}
        rows={2}
        aria-label="Question"
        disabled={!hasConnection}
      />
      <Button variant="primary" onClick={send} disabled={!canSend} loading={streaming} icon={<Send size={16} />} aria-label="Send">
        {streaming ? 'Streaming' : 'Send'}
      </Button>
      {!hasConnection && <p className="muted composer-hint">Add and select a connection to start asking.</p>}
    </div>
  );
}