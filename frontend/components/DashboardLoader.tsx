'use client';
import dynamic from 'next/dynamic';
import { Skeleton } from './ui';

// The terminal is entirely live, per-browser state (remembered tab/symbol, WebSocket, polling), so it
// renders on the client only. That also means it can read localStorage during init with no hydration mismatch.
const Dashboard = dynamic(() => import('./Dashboard'), {
  ssr: false,
  loading: () => (
    <div className="flex h-screen">
      <Skeleton className="m-2 w-[220px]" />
      <div className="flex-1 space-y-2 p-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-[70vh] w-full" />
      </div>
    </div>
  ),
});

export default function DashboardLoader() {
  return <Dashboard />;
}
