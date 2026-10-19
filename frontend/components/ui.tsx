'use client';
import { useState, type ButtonHTMLAttributes, type ReactNode } from 'react';

type Tone = 'neutral' | 'primary' | 'danger' | 'warn';

const TONES: Record<Tone, string> = {
  neutral: 'bg-card border-line text-dim hover:text-foreground',
  primary: 'bg-[#1e3a5f] border-[#2a4a6f] text-accent-soft hover:bg-[#24466f]',
  danger: 'bg-[#3a1414] border-[#5a2020] text-down hover:bg-[#4a1a1a]',
  warn: 'bg-[#3a2a0a] border-[#5a4210] text-warn hover:bg-[#4a360e]',
};

export function Btn({
  tone = 'neutral', small = false, className = '', ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone; small?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      className={`rounded-md border font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
        small ? 'px-2.5 py-1 text-[11px]' : 'px-3.5 py-1.5 text-xs'
      } ${TONES[tone]} ${className}`}
    />
  );
}

/** `collapsible` makes the header a toggle; `defaultOpen` sets the starting state. */
export function Card({ title, right, children, className = '', collapsible = false, defaultOpen = true }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
  collapsible?: boolean; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const shown = !collapsible || open;
  return (
    <section className={`rounded-lg border border-line bg-card ${className}`}>
      {(title || right) && (
        <header className={`flex items-center justify-between gap-3 px-3 py-2 ${shown ? 'border-b border-line' : ''}`}>
          {collapsible ? (
            <button
              type="button"
              onClick={() => setOpen(o => !o)}
              aria-expanded={open}
              className="flex flex-1 items-center gap-2 text-left text-xs font-bold uppercase tracking-wide text-dim hover:text-foreground"
            >
              <span className={`inline-block text-[10px] transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
              {title}
            </button>
          ) : (
            <h3 className="text-xs font-bold uppercase tracking-wide text-dim">{title}</h3>
          )}
          {right}
        </header>
      )}
      {shown && <div className="p-3">{children}</div>}
    </section>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-card px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-bold ${tone ?? ''}`}>{value}</div>
    </div>
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-7 w-full" />)}
    </div>
  );
}

/** Inline problem box: says what happened and offers a retry. Used instead of silently showing nothing. */
export function ErrorBox({ message, onRetry, stale = false }: { message: string; onRetry?: () => void; stale?: boolean }) {
  return (
    <div role="alert" className="flex items-start justify-between gap-3 rounded-md border border-[#5a2020] bg-[#1f0a0a] px-3 py-2 text-xs text-down">
      <span>
        {message}
        {stale && <span className="ml-1 text-dim">Showing the last data received.</span>}
      </span>
      {onRetry && <Btn small tone="danger" onClick={onRetry}>Retry</Btn>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-muted">{children}</div>;
}

export function Segmented<T extends string>({ options, value, onChange }: {
  options: readonly T[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-0.5 rounded-md border border-line bg-card p-0.5" role="group">
      {options.map(o => (
        <button
          key={o}
          type="button"
          onClick={() => onChange(o)}
          aria-pressed={value === o}
          className={`rounded px-2.5 py-1 text-[11px] transition-colors ${
            value === o ? 'bg-[#1e293b] font-semibold text-foreground' : 'text-muted hover:text-dim'
          }`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

export function DirBadge({ dir }: { dir: string }) {
  const cls = dir === 'BUY'
    ? 'bg-green-900/60 text-green-400 border-green-800'
    : dir === 'SELL' ? 'bg-red-900/60 text-red-400 border-red-800' : 'bg-gray-800 text-gray-400 border-gray-700';
  return <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${cls}`}>{dir}</span>;
}

export function ScoreBars({ score, dir, thick = false }: { score: number; dir: string; thick?: boolean }) {
  const on = dir === 'BUY' ? 'bg-up' : dir === 'SELL' ? 'bg-down' : 'bg-muted';
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`Score ${score} of 5`}>
      {[1, 2, 3, 4, 5].map(n => (
        <span key={n} className={`${thick ? 'h-1.5 w-full min-w-3' : 'h-[7px] w-[7px]'} rounded-sm ${n <= score ? on : 'bg-[#1e1e2e]'}`} />
      ))}
    </span>
  );
}

export function Updated({ at, refreshing }: { at: number | null; refreshing?: boolean }) {
  if (!at && !refreshing) return null;
  return (
    <span className="text-[10px] text-muted">
      {refreshing ? 'Updating…' : `Updated ${new Date(at!).toLocaleTimeString('en-IN', { hour12: false })}`}
    </span>
  );
}
