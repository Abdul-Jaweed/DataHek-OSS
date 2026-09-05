import { Database, FileText, Gauge, History, MessageSquare, Settings } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

const NAV: NavItem[] = [
  { to: '/chat', label: 'Chat', icon: <MessageSquare size={20} /> },
  { to: '/connections', label: 'Connections', icon: <Database size={20} /> },
  { to: '/conversations', label: 'Conversations', icon: <History size={20} /> },
  { to: '/prompts', label: 'Prompts', icon: <FileText size={20} /> },
  { to: '/evaluations', label: 'Evaluations', icon: <Gauge size={20} /> },
  { to: '/settings', label: 'Settings', icon: <Settings size={20} /> },
];

export function Sidebar() {
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="sidebar-brand">
        <span className="brand-mark">⚡</span>
        <span>
          Data<span className="brand-accent">Hek</span> <span className="caption">OSS</span>
        </span>
      </div>
      <ul className="sidebar-nav">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}
            >
              {item.icon}
              <span>{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}