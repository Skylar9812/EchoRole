'use client';
import {useT, useErrorText} from '@/i18n/context';


import { useEffect, useState, type ReactNode } from 'react';

/** Shared presentation only; reconnecting never retries a mutation. */
export function Feedback({ children }: { children: ReactNode }) {
 const tr=useT();

  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    update();
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  return <div data-feedback>
    {offline && <p role="status" data-offline>{tr("You’re offline. Your view may be out of date. Updates resume when your connection returns.")}</p>}
    {children}
  </div>;
}

export function ConnectionNotice({ error, onRetry }: { error: string; onRetry: () => void }) {
 const tr=useT(), errorText=useErrorText();

  return <div role="alert" data-notice>
    <p>{tr("Updates unavailable:")} {errorText(error)}{tr(". Displayed data may be stale.")}</p>
    <button onClick={onRetry}>{tr("Retry room updates")}</button>
  </div>;
}
