import {
  ChatCircleText,
  ClockCounterClockwise,
  Database,
  FileText,
  Gauge,
  GearSix,
  Lightning,
  ShieldCheck,
} from '@phosphor-icons/react';
import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

const NAV: NavItem[] = [
  { to: '/chat', label: 'Chat', icon: <ChatCircleText size={20} /> },
  { to: '/connections', label: 'Connections', icon: <Database size={20} /> },
  { to: '/conversations', label: 'Conversations', icon: <ClockCounterClockwise size={20} /> },
  { to: '/prompts', label: 'Prompts', icon: <FileText size={20} /> },
  { to: '/approvals', label: 'Approvals', icon: <ShieldCheck size={20} /> },
  { to: '/evaluations', label: 'Evaluations', icon: <Gauge size={20} /> },
  { to: '/settings', label: 'Settings', icon: <GearSix size={20} /> },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 px-5 py-4">
        <Lightning size={22} weight="fill" className="text-brand-strong" />
        <span className="text-[15px] font-semibold text-foreground">
          Data<span className="text-brand-strong">Hek</span>
        </span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted">OSS</span>
      </div>
      <nav className="flex-1 px-2" aria-label="Main">
        <ul className="space-y-1">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                onClick={onNavigate}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-150',
                    isActive
                      ? 'bg-surface-2 text-brand-strong'
                      : 'text-muted hover:bg-surface-2 hover:text-foreground',
                  ].join(' ')
                }
              >
                {item.icon}
                <span>{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}