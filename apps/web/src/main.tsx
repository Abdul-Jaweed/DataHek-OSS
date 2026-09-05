import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { AuthGate } from './components/layout/AuthGate';
import { ChatPage } from './features/ChatPage';
import { ConnectionsPage } from './features/ConnectionsPage';
import { ConversationsPage } from './features/ConversationsPage';
import { PromptsPage } from './features/PromptsPage';
import { EvaluationsPage } from './features/EvaluationsPage';
import { SettingsPage } from './features/SettingsPage';
import { LandingPage } from './features/LandingPage';
import { LoginPage } from './features/LoginPage';
import './styles/globals.css';

function AppPage({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <AuthGate>{children}</AuthGate>
    </AppShell>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/chat" element={<AppPage><ChatPage /></AppPage>} />
        <Route path="/connections" element={<AppPage><ConnectionsPage /></AppPage>} />
        <Route path="/conversations" element={<AppPage><ConversationsPage /></AppPage>} />
        <Route path="/prompts" element={<AppPage><PromptsPage /></AppPage>} />
        <Route path="/evaluations" element={<AppPage><EvaluationsPage /></AppPage>} />
        <Route path="/settings" element={<AppPage><SettingsPage /></AppPage>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);