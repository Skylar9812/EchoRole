'use client';

import { useEffect, useState, type ReactNode } from 'react';

/** Shared presentation only; reconnecting never retries a mutation. */
export function Feedback({ children }: { children: ReactNode }) {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    update();
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  return <div data-feedback>
    {offline && <p role="status" data-offline>You’re offline. Your view may be out of date. Updates resume when your connection returns.</p>}
    {children}
  </div>;
}

export function ConnectionNotice({ error, onRetry }: { error: string; onRetry: () => void }) {
  return <div role="alert" data-notice>
    <p>Updates unavailable: {error}. Displayed data may be stale.</p>
    <button onClick={onRetry}>Retry room updates</button>
  </div>;
}
