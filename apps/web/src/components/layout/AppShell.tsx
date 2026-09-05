import { List, Monitor, Moon, SidebarSimple, Sun } from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { applyTheme, useStore, type ThemePreference } from '../../store/use-store';
import { cn } from '../../lib/utils';
import { Sidebar } from './Sidebar';

const THEMES: { value: ThemePreference; label: string; icon: ReactNode }[] = [
  { value: 'light', label: 'Light', icon: <Sun size={15} /> },
  { value: 'dark', label: 'Dark', icon: <Moon size={15} /> },
  { value: 'system', label: 'System', icon: <Monitor size={15} /> },
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
          'sidebar-shell hidden shrink-0 overflow-hidden border-r border-border bg-surface md:block',
          sidebarHidden ? 'w-0 border-r-0' : 'w-60',
        )}
      >
        <div className="w-60">
          <Sidebar />
        </div>
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-60 border-r border-border bg-surface shadow-lg">
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/90 px-3 backdrop-blur sm:px-4">
          <button
            className="cursor-pointer rounded-md p-2 text-muted hover:bg-surface-2 hover:text-foreground md:hidden"
            onClick={() => setDrawerOpen((v) => !v)}
            aria-label="Toggle navigation"
          >
            <List size={20} />
          </button>

          {/* Sidebar hide/slide toggle (desktop) */}
          <button
            className="hidden cursor-pointer rounded-md p-2 text-muted hover:bg-surface-2 hover:text-foreground md:inline-flex"
            onClick={toggleSidebar}
            aria-label={sidebarHidden ? 'Show sidebar' : 'Hide sidebar'}
            title={sidebarHidden ? 'Show sidebar' : 'Hide sidebar'}
          >
            <SidebarSimple size={19} weight={sidebarHidden ? 'bold' : 'regular'} />
          </button>

          <div className="ml-auto flex items-center gap-3">
            {headerRight}

            {/* Theme toggle: Light / Dark / System */}
            <div
              className="flex rounded-md bg-surface-2 p-0.5"
              role="group"
              aria-label="Theme"
            >
              {THEMES.map((t) => (
                <button
                  key={t.value}
                  className={cn(
                    'flex h-7 w-8 cursor-pointer items-center justify-center rounded-[6px] transition-colors duration-150',
                    theme === t.value
                      ? 'bg-surface text-brand-strong shadow-sm'
                      : 'text-faint hover:text-foreground',
                  )}
                  onClick={() => setTheme(t.value)}
                  title={t.label}
                  aria-label={`${t.label} mode`}
                  aria-pressed={theme === t.value}
                >
                  {t.icon}
                </button>
              ))}
            </div>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}