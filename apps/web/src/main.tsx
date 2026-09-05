import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { ChatPage } from './features/ChatPage';
import { ConnectionsPage } from './features/ConnectionsPage';
import { EmptyState } from './components/ui/EmptyState';
import './styles/base.css';
import './styles/app.css';
import './components/layout/shell.css';
import './components/chat/chat.css';

function Placeholder({ title }: { title: string }) {
  return <EmptyState title={title} description="Screen specified in docs/frontend — implemented next." />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/conversations" element={<Placeholder title="Conversations" />} />
          <Route path="/prompts" element={<Placeholder title="Prompts" />} />
          <Route path="/evaluations" element={<Placeholder title="Evaluations" />} />
          <Route path="/settings" element={<Placeholder title="Settings" />} />
          <Route path="*" element={<EmptyState title="Page not found" description="That route does not exist." />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  </StrictMode>,
);