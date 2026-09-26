'use client';
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';

type Kind = 'success' | 'error' | 'info';
interface ToastItem { id: number; kind: Kind; text: string }

interface ToastApi {
  success: (text: string) => void;
  error: (text: string) => void;
  info: (text: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

const STYLE: Record<Kind, string> = {
  success: 'border-[#1e4d1e] bg-[#0c1f0c] text-up',
  error: 'border-[#5a2020] bg-[#1f0a0a] text-down',
  info: 'border-[#1e3a5f] bg-[#0a1220] text-accent-soft',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const push = useCallback((kind: Kind, text: string) => {
    const id = nextId.current++;
    setItems(prev => [...prev.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems(prev => prev.filter(t => t.id !== id)), kind === 'error' ? 8000 : 4000);
  }, []);

  const api = useMemo<ToastApi>(() => ({
    success: t => push('success', t),
    error: t => push('error', t),
    info: t => push('info', t),
  }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {items.map(t => (
          <div key={t.id} role={t.kind === 'error' ? 'alert' : 'status'}
            className={`pointer-events-auto rounded-md border px-3 py-2 text-xs shadow-lg ${STYLE[t.kind]}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
