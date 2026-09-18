import {
  BookmarkSimple,
  ChatCircleText,
  ClockCounterClockwise,
  Database,
  FileText,
  Gauge,
  GearSix,
  Lightning,
  Plus,
  Ruler,
  ShieldCheck,
} from '@phosphor-icons/react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../../api/client';
import { cn } from '../../lib/utils';
import { useStore } from '../../store/use-store';

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    label: 'Workspace',
    items: [
      { to: '/chat', label: 'Chat', icon: <ChatCircleText size={16} /> },
      { to: '/connections', label: 'Connections', icon: <Database size={16} /> },
      { to: '/conversations', label: 'Conversations', icon: <ClockCounterClockwise size={16} /> },
      { to: '/saved', label: 'Saved', icon: <BookmarkSimple size={16} /> },
    ],
  },
  {
    label: 'Governance',
    items: [
      { to: '/approvals', label: 'Approvals', icon: <ShieldCheck size={16} /> },
      { to: '/metrics', label: 'Semantics', icon: <Ruler size={16} /> },
      { to: '/prompts', label: 'Prompts', icon: <FileText size={16} /> },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/evaluations', label: 'Evaluations', icon: <Gauge size={16} /> },
      { to: '/settings', label: 'Settings', icon: <GearSix size={16} /> },
    ],
  },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { streaming, newConversation } = useStore();
  const [pendingApprovals, setPendingApprovals] = useState(0);

  useEffect(() => {
    api
      .listApprovals()
      .then((rows) => setPendingApprovals(rows.filter((r) => r.status === 'pending').length))
      .catch(() => {});
  }, [pathname]);

  const startNewChat = () => {
    newConversation();
    navigate('/chat');
    onNavigate?.();
  };

  return (
    <div className="flex h-full flex-col justify-between px-3 py-3.5">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2.5 px-1 py-1">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm bg-brand text-brand-contrast">
            <Lightning size={15} weight="bold" />
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="text-[13px] font-bold uppercase leading-none tracking-tight text-foreground">
              DataHek
            </span>
            <span className="mt-1 truncate font-mono text-[9px] font-medium uppercase tracking-[0.14em] text-faint">
              OSS Analytics Workbench
            </span>
          </div>
        </div>

        <button
          className="flex h-9 w-full cursor-pointer items-center justify-center gap-1.5 rounded-md bg-brand text-[12.5px] font-semibold text-brand-contrast transition-colors duration-150 hover:bg-brand-hover disabled:pointer-events-none disabled:opacity-40"
          onClick={startNewChat}
          disabled={streaming}
        >
          <Plus size={15} weight="bold" />
          New chat
        </button>
      </div>

      <nav className="mt-4 flex flex-1 flex-col gap-4 overflow-y-auto" aria-label="Main">
        {GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-0.5">
            <span className="px-2.5 py-1 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-faint">
              {group.label}
            </span>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2.5 rounded-sm px-2.5 py-1.5 text-[13px] transition-colors duration-150',
                    isActive
                      ? 'bg-surface-2 font-medium text-foreground shadow-[inset_2px_0_0_var(--brand)]'
                      : 'text-muted hover:bg-surface-2/60 hover:text-foreground',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span className={isActive ? 'text-brand-strong' : 'text-faint'}>{item.icon}</span>
                    <span className="flex-1">{item.label}</span>
                    {item.to === '/approvals' && pendingApprovals > 0 && (
                      <span className="rounded-sm border border-border bg-surface-2 px-1.5 font-mono text-[10px] font-semibold text-foreground">
                        {pendingApprovals}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="mt-3 border-t border-border px-1 pt-3">
        <div className="flex items-center gap-2 font-mono text-[11px] text-faint">
          <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
          <span className="uppercase tracking-wider">Read-only enforced</span>
        </div>
      </div>
    </div>
  );
}
