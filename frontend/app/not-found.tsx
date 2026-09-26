import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3">
      <h2 className="text-lg font-bold">Page not found</h2>
      <Link href="/" className="rounded-md border border-[#2a4a6f] bg-[#1e3a5f] px-4 py-1.5 text-xs font-semibold text-accent-soft">Back to the terminal</Link>
    </div>
  );
}
