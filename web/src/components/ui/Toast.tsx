import { create } from 'zustand';
import s from './Toast.module.css';

export interface ToastItem {
  id: number;
  message: string;
  action?: { label: string; onClick: () => void };
}

interface ToastStore {
  toasts: ToastItem[];
  push: (t: Omit<ToastItem, 'id'>, ms?: number) => void;
  dismiss: (id: number) => void;
}

let seq = 0;
export const useToasts = create<ToastStore>()((set, get) => ({
  toasts: [],
  push: (t, ms = 3200) => {
    const id = ++seq;
    set({ toasts: [...get().toasts.slice(-2), { ...t, id }] });
    window.setTimeout(() => get().dismiss(id), ms);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((x) => x.id !== id) }),
}));

export const toast = (message: string, action?: ToastItem['action']) =>
  useToasts.getState().push({ message, action });

export function ToastRegion() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div className={s.region} role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={s.toast}>
          <span>{t.message}</span>
          {t.action ? (
            <button
              type="button"
              className={s.action}
              onClick={() => {
                t.action?.onClick();
                useToasts.getState().dismiss(t.id);
              }}
            >
              {t.action.label}
            </button>
          ) : (
            <span className={s.spacer} />
          )}
        </div>
      ))}
    </div>
  );
}
