import { Menu } from 'lucide-react';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';

export interface AppShellProps {
  headerRight?: ReactNode;
  children: ReactNode;
}

export function AppShell({ headerRight, children }: AppShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="shell">
      <div className={`shell-sidebar${drawerOpen ? ' open' : ''}`}>
        <Sidebar />
      </div>
      {drawerOpen && <div className="shell-overlay" onClick={() => setDrawerOpen(false)} />}
      <div className="shell-main">
        <header className="shell-header">
          <button className="btn btn-icon shell-menu" onClick={() => setDrawerOpen((v) => !v)} aria-label="Toggle navigation">
            <Menu size={20} />
          </button>
          <div className="shell-header-right">{headerRight}</div>
        </header>
        <main className="shell-content">{children}</main>
      </div>
    </div>
  );
}