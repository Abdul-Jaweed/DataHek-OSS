import { List, SidebarSimple } from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { applyTheme, useStore, type ThemePreference } from '../../store/use-store';
import { cn } from '../../lib/utils';
import { Toaster } from '../ui/toaster';
import { Sidebar } from './Sidebar';

const THEMES: { value: ThemePreference; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

export interface AppShellProps {
  headerRight?: ReactNode;
  children: ReactNode;
}

export function AppShell({ headerRight, children }: AppShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { theme, setTheme, sidebarHidden, toggleSidebar } = useStore();

  useEffect(() => {
    applyTheme(theme);
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      if (useStore.getState().theme === 'system') applyTheme('system');
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [theme]);

  return (
    <div className="theme-transition flex h-screen overflow-hidden bg-background">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          'sidebar-shell hidden shrink-0 overflow-hidden border-r border-rail-border bg-rail md:block',
          sidebarHidden ? 'w-0 border-r-0' : 'w-[236px]',
        )}
      >
        <div className="w-[236px]">
          <Sidebar />
        </div>
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-[8px]" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[236px] border-r border-rail-border bg-rail shadow-lg">
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-4 sm:px-6">
          <button
            className="cursor-pointer rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-foreground md:hidden"
            onClick={() => setDrawerOpen((v) => !v)}
            aria-label="Toggle navigation"
          >
            <List size={18} />
          </button>

          {/* Sidebar hide/slide toggle (desktop) */}
          <button
            className="hidden cursor-pointer rounded-sm p-1.5 text-muted hover:bg-surface-2 hover:text-foreground md:inline-flex"
            onClick={toggleSidebar}
            aria-label={sidebarHidden ? 'Show sidebar' : 'Hide sidebar'}
            title={sidebarHidden ? 'Show sidebar' : 'Hide sidebar'}
          >
            <SidebarSimple size={17} weight={sidebarHidden ? 'bold' : 'regular'} />
          </button>

          <div className="ml-auto flex items-center gap-3">
            {headerRight}

            {/* Theme switcher: Light / Dark / System */}
            <div
              className="flex items-center rounded-md border border-border bg-surface-2 p-0.5"
              role="group"
              aria-label="Theme"
            >
              {THEMES.map((t) => (
                <button
                  key={t.value}
                  className={cn(
                    'h-6 cursor-pointer rounded-sm border px-2 font-mono text-[11px] transition-colors duration-150',
                    theme === t.value
                      ? 'border-border bg-surface font-semibold text-foreground'
                      : 'border-transparent text-muted hover:text-foreground',
                  )}
                  onClick={() => setTheme(t.value)}
                  aria-pressed={theme === t.value}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>

      <Toaster />
    </div>
  );
}
