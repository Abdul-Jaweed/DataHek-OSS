import { create } from 'zustand';

export interface Toast {
  id: number;
  message: string;
  icon: 'success' | 'error';
}

interface ToastState {
  toasts: Toast[];
  push: (message: string, icon: Toast['icon']) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (message, icon) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts.slice(-2), { id, message, icon }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 2000);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export function toast(message: string, icon: Toast['icon'] = 'success') {
  useToastStore.getState().push(message, icon);
}
