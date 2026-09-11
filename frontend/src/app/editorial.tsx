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

export function Doorway() {
  return <div className={styles.doorway} data-illustration-slot="doorway" aria-hidden="true"><span /><i /></div>;
}
