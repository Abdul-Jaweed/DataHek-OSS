import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { api } from '../../api/client';
import { useStore } from '../../store/use-store';

let authMode: string | null = null;
let authModeLoaded = false;

/** Redirects to /login when the server enforces auth and no token is stored. */
export function AuthGate({ children }: { children: ReactNode }) {
  const apiKey = useStore((s) => s.apiKey);
  const [checking, setChecking] = useState(!authModeLoaded);

  useEffect(() => {
    if (authModeLoaded) return;
    api
      .health()
      .then((h) => {
        authMode = h.auth_mode ?? 'none';
        authModeLoaded = true;
        setChecking(false);
      })
      .catch(() => {
        authMode = 'none';
        authModeLoaded = true;
        setChecking(false);
      });
  }, []);

  if (checking) return null;
  if (authMode === 'local' && !apiKey) return <Navigate to="/login" replace />;
  return <>{children}</>;
}