'use client';
import { useEffect } from 'react';

export default function Error({ error, unstable_retry }: { error: Error & { digest?: string }; unstable_retry: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return (
    <div className="flex h-screen items-center justify-center p-6">
      <div role="alert" className="max-w-md rounded-lg border border-[#5a2020] bg-[#1f0a0a] p-5 text-center">
        <h2 className="text-base font-bold text-down">Something went wrong</h2>
        <p className="mt-2 text-xs text-dim">{error.message || 'An unexpected error occurred.'}</p>
        <div className="mt-4 flex justify-center gap-2">
          <button type="button" onClick={() => unstable_retry()} className="rounded-md border border-[#2a4a6f] bg-[#1e3a5f] px-4 py-1.5 text-xs font-semibold text-accent-soft">Try again</button>
          <button type="button" onClick={() => window.location.reload()} className="rounded-md border border-line bg-card px-4 py-1.5 text-xs text-dim">Reload page</button>
        </div>
      </div>
    </div>
  );
}
