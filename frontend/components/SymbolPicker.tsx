'use client';
import { useEffect, useId, useMemo, useRef, useState } from 'react';

const MAX_SHOWN = 60;

/** Searchable dropdown: type to filter, arrows + Enter to pick. Enter on text not in the list still submits it. */
export function SymbolPicker({ value, options, onPick, loading = false, label }: {
  value: string; options: string[]; onPick: (s: string) => void; loading?: boolean; label: string;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return options.slice(0, MAX_SHOWN);
    const starts = options.filter(o => o.startsWith(q));
    const contains = options.filter(o => !o.startsWith(q) && o.includes(q));
    return [...starts, ...contains].slice(0, MAX_SHOWN);
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!boxRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${hi}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [hi]);

  const pick = (s: string) => {
    const sym = s.trim().toUpperCase();
    if (sym) onPick(sym);
    setQuery('');
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setHi(h => Math.min(h + 1, matches.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(h - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(open && matches[hi] ? matches[hi] : query); }
    else if (e.key === 'Escape') { setOpen(false); setQuery(''); }
  };

  return (
    <div ref={boxRef} className="relative w-full sm:w-56">
      <input
        role="combobox"
        aria-label={label}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && matches[hi] ? `${listId}-${hi}` : undefined}
        value={open ? query : value}
        placeholder={value}
        onFocus={() => { setOpen(true); setQuery(''); setHi(0); }}
        onChange={e => { setQuery(e.target.value.toUpperCase()); setOpen(true); setHi(0); }}
        onKeyDown={onKey}
        className="w-full rounded-md border border-line bg-card py-1.5 pl-2.5 pr-7 text-sm font-semibold outline-none focus:border-accent"
      />
      <button
        type="button"
        tabIndex={-1}
        aria-label="Show symbols"
        onClick={() => setOpen(o => !o)}
        className="absolute inset-y-0 right-0 px-2 text-[10px] text-muted hover:text-dim"
      >▼</button>

      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-line bg-panel-2 py-1 text-xs shadow-lg shadow-black/40"
        >
          {matches.map((s, i) => (
            <li
              key={s}
              id={`${listId}-${i}`}
              data-i={i}
              role="option"
              aria-selected={s === value}
              onMouseDown={e => { e.preventDefault(); pick(s); }}
              onMouseEnter={() => setHi(i)}
              className={`flex cursor-pointer justify-between px-2.5 py-1.5 ${i === hi ? 'bg-accent/20 text-foreground' : 'text-dim'}`}
            >
              <span className="font-semibold">{s}</span>
              {s === value && <span className="text-accent-soft">✓</span>}
            </li>
          ))}
          {matches.length === 0 && (
            <li className="px-2.5 py-1.5 text-muted">
              {loading ? 'Loading symbols…' : query ? <>Press Enter to load <b className="text-dim">{query}</b></> : 'No symbols'}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
