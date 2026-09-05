import { create } from 'zustand';
import { api, clearApiKey, getApiKey, setApiKey } from '../api/client';
import type { Connection } from '../api/types';
import type { Message } from '../components/chat/MessageBubble';

export type ThemePreference = 'light' | 'dark' | 'system';
export type Theme = 'light' | 'dark';

const THEME_KEY = 'datahek-theme';
const SIDEBAR_KEY = 'datahek-sidebar-hidden';

function mediaDark() {
  return window.matchMedia('(prefers-color-scheme: dark)');
}

export function resolveTheme(pref: ThemePreference): Theme {
  return pref === 'system' ? (mediaDark().matches ? 'dark' : 'light') : pref;
}

export function applyTheme(pref: ThemePreference) {
  const theme = resolveTheme(pref);
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

interface DataHekState {
  connections: Connection[];
  selectedConnectionId: string | null;
  conversationId: string | null;
  messages: Message[];
  streaming: boolean;
  apiKey: string | null;
  loaded: boolean;

  theme: ThemePreference;
  sidebarHidden: boolean;

  loadConnections: () => Promise<void>;
  selectConnection: (id: string | null) => void;
  setConversation: (id: string | null) => void;
  setMessages: (messages: Message[]) => void;
  appendMessage: (message: Message) => void;
  patchMessage: (id: string, updater: (current: Message) => Partial<Message>) => void;
  setStreaming: (streaming: boolean) => void;
  newConversation: () => void;
  saveApiKey: (key: string) => void;
  removeApiKey: () => void;

  setTheme: (pref: ThemePreference) => void;
  toggleSidebar: () => void;
}

const initialTheme = (localStorage.getItem(THEME_KEY) as ThemePreference | null) ?? 'system';

export const useStore = create<DataHekState>((set) => ({
  connections: [],
  selectedConnectionId: null,
  conversationId: null,
  messages: [],
  streaming: false,
  apiKey: getApiKey(),
  loaded: false,

  theme: initialTheme,
  sidebarHidden: localStorage.getItem(SIDEBAR_KEY) === '1',

  loadConnections: async () => {
    try {
      const conns = await api.listConnections();
      set((s) => ({
        connections: conns,
        selectedConnectionId: s.selectedConnectionId ?? conns[0]?.id ?? null,
        loaded: true,
      }));
    } catch {
      set({ loaded: true });
    }
  },

  selectConnection: (id) => set({ selectedConnectionId: id }),
  setConversation: (id) => set({ conversationId: id }),
  setMessages: (messages) => set({ messages }),
  appendMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),
  patchMessage: (id, updater) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...updater(m) } : m)),
    })),
  setStreaming: (streaming) => set({ streaming }),
  newConversation: () => set({ messages: [], conversationId: null }),

  saveApiKey: (key) => {
    setApiKey(key);
    set({ apiKey: key });
  },
  removeApiKey: () => {
    clearApiKey();
    set({ apiKey: null });
  },

  setTheme: (pref) => {
    localStorage.setItem(THEME_KEY, pref);
    applyTheme(pref);
    set({ theme: pref });
  },
  toggleSidebar: () =>
    set((s) => {
      const hidden = !s.sidebarHidden;
      localStorage.setItem(SIDEBAR_KEY, hidden ? '1' : '0');
      return { sidebarHidden: hidden };
    }),
}));

/** Convenience: resolve the active conversation id, creating one if needed. */
export async function ensureConversation(): Promise<string | null> {
  const { conversationId, setConversation } = useStore.getState();
  if (conversationId) return conversationId;
  try {
    const conv = await api.createConversation();
    setConversation(conv.id);
    return conv.id;
  } catch {
    return null;
  }
}