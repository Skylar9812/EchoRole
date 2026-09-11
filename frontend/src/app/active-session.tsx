'use client';

import type { ReactNode } from 'react';
import type { Profile, Room, Member, Session, TurnStatus, PrivateState } from '@/lib/contracts';
import { Brand } from './editorial';
import base from './landing.module.css';
import styles from './active-session.module.css';

type Props = {
  profile: Profile; score: number; room: Room; members: Member[];
  session: Session; turn: TurnStatus; role?: PrivateState['role_name'];
  pollError: string; busy: boolean; onRefresh: () => void; onLeave: () => void;
  feedback: ReactNode; profileForm: ReactNode; setup: ReactNode; brief: ReactNode;
  coach: ReactNode; guidance: ReactNode; chat: ReactNode; peer: ReactNode;
  action: ReactNode; history: ReactNode;
};

// Presentation only. Server status and the workflow's existing mutation handlers
// remain the authority for what can be submitted, completed, or recovered.
export default function ActiveSession(p: Props) {
  const { turn: t, session: s } = p;
  const role = p.role === 'role_a' ? 'Role A' : p.role === 'role_b' ? 'Role B' : 'Role pending';
  const status = t.state === 'uncertain' ? 'Recovery required'
    : t.state === 'generating' ? 'Generating the next scene'
    : t.state === 'advanced' ? 'Advanced'
    : t.submitted && t.other_submitted ? 'Ready to advance'
    : t.submitted ? 'Waiting for partner' : 'Action required';
  return <div className={`${base.page} ${styles.page}`}>
    <a className={base.skip} href="#current-scene">Skip to current situation</a>
    <div className={`${base.shell} ${styles.shell}`}>
      <header className={`${base.header} ${styles.header}`} id="top">
        <Brand />
        <div className={styles.sessionLabel}><span>ACTIVE SESSION</span><p>{role} <i aria-hidden="true">·</i> Turn {t.current_turn}</p></div>
        <div className={styles.roomCode}><span>ROOM CODE</span><strong>{p.room.invite_code}</strong></div>
      </header>
      <div className={styles.statusBar} role="status" aria-live="polite" aria-atomic="true">
        <strong>{status}</strong><span>You: {t.submitted ? 'Submitted' : 'Action required'}</span>
        <span>Partner: {t.other_submitted ? 'Submitted' : 'Waiting'}</span>
        <span>{p.members.length} participant{p.members.length === 1 ? '' : 's'}</span>
      </div>
      <div className={styles.feedback}>{p.feedback}{p.pollError && <div role="alert"><p>Updates unavailable: {p.pollError}. Displayed data may be stale.</p><button onClick={p.onRefresh}>Retry room updates</button></div>}</div>
      <main className={styles.workspace}>
        <article className={styles.scene} id="current-scene">
          <span className="section-label">TURN {String(t.current_turn).padStart(2, '0')} / THE CONVERSATION</span>
          <h1>Current Situation</h1>
          <p className={styles.sceneTitle}>{s.title} — Turn {t.current_turn}</p>
          <div className={styles.sceneRule} aria-hidden="true"><span /></div>
          <p className={styles.story}>{t.current_situation}</p>
        </article>
        <div className={styles.brief}>{p.brief}</div>
        <div className={styles.move}>{p.action}</div>
        <aside className={styles.guidance}>{p.guidance}</aside>
        <div className={styles.coach}>{p.coach}</div>
        <div className={styles.chat}><span className="section-label">THE SHARED SPACE</span>{p.chat}</div>
        <div className={styles.history}>{p.history}</div>
        <aside className={styles.context} aria-label="Session context and utilities">
          <span className="section-label">YOUR PERSPECTIVE</span>
          <div className={styles.identity}><span aria-hidden="true">{p.profile.display_name.slice(0, 1).toUpperCase()}</span><div><h2>{p.profile.display_name}</h2><p>{role}</p></div></div>
          <p className={styles.score}>Peer score: {p.score} points</p>
          <section className={styles.contextGroup}><h3>In this room</h3>
            <ul>{p.members.map(m => <li key={m.user_id}><span aria-hidden="true" />{m.nickname || 'Participant'}{m.user_id === p.profile.user_id && <small>You</small>}</li>)}</ul>
            {p.members.length === 1 && <p>Waiting for another participant. Share the invite code.</p>}
          </section>
          <section className={styles.contextGroup}><span className="section-label">THE SCENARIO</span><h3>{s.title}</h3><details><summary>Scenario context</summary><p>{s.context}</p><p>{s.conflict}</p></details></section>
          <div className={styles.contextGroup}>{p.profileForm}</div>
          <details className={styles.utilities}><summary>Room utilities</summary>{p.setup}</details>
          <div className={styles.utilityButtons}><button onClick={p.onRefresh}>Refresh status</button><button disabled={p.busy} onClick={p.onLeave}>Leave room</button></div>
          <p className={styles.note}>A little space<br />for another perspective.</p>
        </aside>
        <div className={styles.peer}>{p.peer}</div>
      </main>
      <footer className={styles.footer}>Listen. Reflect. <em>Choose another way forward.</em></footer>
    </div>
  </div>;
}
