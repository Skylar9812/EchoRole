import Image from 'next/image';
import styles from './landing.module.css';

/** Shared editorial primitives, using the approved landing markup and styles. */
export function Brand() {
  return <a className={styles.brand} href="#top" aria-label="EchoRole home">
    <img src="/echorole-icon.png" width="54" height="54" alt="" />
    <span><strong>EchoRole</strong><small>CONVERSATION SIMULATIONS</small></span>
  </a>;
}

export function Arrow() {
  return <svg width="22" height="16" viewBox="0 0 22 16" fill="none" aria-hidden="true"><path d="M1 8h19M14 2l6 6-6 6" stroke="currentColor" strokeWidth="1.3" /></svg>;
}

export function Doorway({ preview = false }: { preview?: boolean }) {
  return <div className={styles.doorway} data-illustration-slot="doorway" aria-hidden="true"><Image src={`/illustrations/${preview ? 'lobby-preview' : 'scenario-arch'}.webp`} alt="" aria-hidden="true" fill sizes="(max-width: 720px) 64px, 104px" className={styles.finalArt} /></div>;
}
