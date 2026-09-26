'use client';
import { useCallback, useState } from 'react';

/**
 * useState that survives a page reload (localStorage). Only use inside client-only components
 * (the dashboard is loaded with ssr:false), so reading storage during init cannot cause a
 * hydration mismatch. Corrupt / blocked storage silently falls back to the default.
 */
export function usePersistentState<T>(key: string, initial: T, validate?: (v: unknown) => v is T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return initial;
      const parsed: unknown = JSON.parse(raw);
      return !validate || validate(parsed) ? (parsed as T) : initial;
    } catch {
      return initial;
    }
  });

  const set = useCallback((next: T | ((prev: T) => T)) => {
    setValue(prev => {
      const resolved = typeof next === 'function' ? (next as (p: T) => T)(prev) : next;
      try { window.localStorage.setItem(key, JSON.stringify(resolved)); } catch { /* storage full / blocked */ }
      return resolved;
    });
  }, [key]);

  return [value, set] as const;
}
