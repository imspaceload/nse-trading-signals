const inr0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtInt = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? '—' : inr0.format(n));
export const fmtPrice = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? '—' : inr2.format(n));
/** Price level: whole rupees for index-sized prices, paise for cheap stocks (IDEA ₹14.38). */
export const fmtLevel = (n: number | null | undefined) => (n != null && Math.abs(n) >= 1000 ? fmtInt(n) : fmtPrice(n));
export const fmtRupee = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? '—' : `₹${inr2.format(n)}`);
export const fmtSigned = (n: number | null | undefined) =>
  n == null || Number.isNaN(n) ? '—' : `${n >= 0 ? '+' : '−'}₹${inr2.format(Math.abs(n))}`;
export const fmtPct = (n: number | null | undefined, signed = true) =>
  n == null || Number.isNaN(n) ? '—' : `${signed && n >= 0 ? '+' : ''}${n.toFixed(2)}%`;

export const pnlClass = (n: number | null | undefined) => ((n ?? 0) >= 0 ? 'text-up' : 'text-down');

/** "12:45:03" style clock for log rows, in the user's locale but always 24h. */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 19);
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    timeZone: 'Asia/Kolkata',
  });
}

export function ago(seconds: number | null | undefined): string {
  if (seconds == null) return 'never';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}
