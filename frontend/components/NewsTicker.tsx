'use client';
import { api } from '../lib/api';
import { usePolling } from '../hooks/usePolling';

export function NewsTicker() {
  const { data } = usePolling(signal => api.getNews(signal), { intervalMs: 10 * 60 * 1000 });
  const items = (data ?? []).filter(i => i.title || i.headline);
  if (items.length === 0) return null;

  return (
    <div className="shrink-0 overflow-hidden whitespace-nowrap border-t border-line bg-panel px-3 py-1" aria-label="Market news">
      <div className="marquee inline-flex gap-10 text-[11px]" style={{ animation: 'marquee 60s linear infinite' }}>
        {items.map((n, i) => {
          const text = n.title ?? n.headline;
          const cls = n.sentiment === 'BULLISH' ? 'text-up' : n.sentiment === 'BEARISH' ? 'text-down' : 'text-dim';
          return n.url
            ? <a key={i} href={n.url} target="_blank" rel="noopener noreferrer" className={cls}>{text}</a>
            : <span key={i} className={cls}>{text}</span>;
        })}
      </div>
    </div>
  );
}
