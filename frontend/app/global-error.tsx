'use client';

// Last-resort boundary: replaces the whole document, so it must render its own <html>/<body> and can't rely on Tailwind.
export default function GlobalError({ error, unstable_retry }: { error: Error & { digest?: string }; unstable_retry: () => void }) {
  return (
    <html lang="en">
      <body style={{ background: '#0a0a14', color: '#e8e8e8', fontFamily: 'system-ui, sans-serif', display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center' }}>
        <div role="alert" style={{ maxWidth: 420, textAlign: 'center', padding: 24 }}>
          <h2 style={{ color: '#ef4444' }}>The terminal crashed</h2>
          <p style={{ color: '#9ca3af', fontSize: 13 }}>{error.message || 'Unexpected error'}</p>
          <button type="button" onClick={() => unstable_retry()} style={{ marginTop: 12, padding: '8px 16px', borderRadius: 6, border: '1px solid #2a4a6f', background: '#1e3a5f', color: '#60a5fa', cursor: 'pointer' }}>
            Reload the terminal
          </button>
        </div>
      </body>
    </html>
  );
}
