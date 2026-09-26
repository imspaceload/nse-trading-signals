'use client';
import { api } from '../lib/api';
import { Btn } from './ui';
import { useToast } from './Toast';
import { errorMessage } from '../lib/api';

/** Top-of-screen problems the user can't miss: API down, or Zerodha logged out. */
export function StatusBanner({ apiDown, apiError, kiteConnected, kiteConfigured, onRetry }: {
  apiDown: boolean;
  apiError?: string;
  kiteConnected: boolean;
  kiteConfigured: boolean;
  onRetry: () => void;
}) {
  const toast = useToast();

  const connectKite = async () => {
    try {
      const { url } = await api.getKiteLoginUrl();
      window.location.assign(url);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  if (apiDown) {
    return (
      <div role="alert" className="flex items-center justify-between gap-3 border-b border-[#5a2020] bg-[#1f0a0a] px-4 py-2 text-xs text-down">
        <span><b>API offline.</b> {(apiError ?? 'Cannot reach the server').replace(/\.$/, '')}. Data on screen may be out of date; retrying automatically.</span>
        <Btn small tone="danger" onClick={onRetry}>Retry now</Btn>
      </div>
    );
  }
  if (kiteConfigured && !kiteConnected) {
    return (
      <div role="status" className="flex items-center justify-between gap-3 border-b border-[#4d3d1e] bg-[#1f1a0a] px-4 py-2 text-xs text-warn">
        <span><b>Zerodha is logged out.</b> Live prices, orders and the auto-trader need today&apos;s login (it expires daily).</span>
        <Btn small tone="warn" onClick={connectKite}>🔑 Connect Zerodha</Btn>
      </div>
    );
  }
  return null;
}
