'use client';
import {useT} from '@/i18n/context';


import Image from 'next/image';
import { Feedback, ConnectionNotice } from './ui-feedback';

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
 const tr=useT();

  const { turn: t, session: s } = p;
  const role = p.role === 'role_a' ? tr("Role A") : p.role === 'role_b' ? tr("Role B") : tr("Role pending");
  const status = t.state === 'uncertain' ? tr("Recovery required")
    : t.state === 'generating' ? tr("Generating the next scene")
    : t.state === 'advanced' ? tr("Advanced")
    : t.submitted && t.other_submitted ? tr("Ready to advance")
    : t.submitted ? tr("Waiting for partner") : tr("Action required");
  return <div data-echorole className={`${base.page} ${styles.page}`}>
    <a className={base.skip} href="#current-scene">{tr("Skip to current situation")}</a>
    <div className={`${base.shell} ${styles.shell}`}>
      <header className={`${base.header} ${styles.header}`} id="top">
        <Brand /><span className="room-language" title={tr("Room language is locked.")}>{p.room.language}</span>
        <div className={styles.sessionLabel}><span>{tr("ACTIVE SESSION")}</span><p>{role} <i aria-hidden="true">·</i> {tr("Turn")} {t.current_turn}</p></div>
        <div className={styles.roomCode}><span>{tr("ROOM CODE")}</span><strong>{p.room.invite_code}</strong></div>
      </header>
      <div className={styles.statusBar} role="status" aria-live="polite" aria-atomic="true">
        <strong>{status}</strong><span>{tr("You:")} {t.submitted ? tr("Submitted") : tr("Action required")}</span>
        <span>{tr("Partner:")} {t.other_submitted ? tr("Submitted") : tr("Waiting")}</span>
        <span>{tr('{0} participants',p.members.length)}</span>
      </div>
      <Feedback>{p.feedback}{p.pollError && <ConnectionNotice error={p.pollError} onRetry={p.onRefresh} />}</Feedback>
      <main className={styles.workspace}>
        <article className={styles.scene} id="current-scene" tabIndex={-1}>
          <span className="section-label">{tr("TURN")} {String(t.current_turn).padStart(2, '0')} {tr("/ THE CONVERSATION")}</span>
          <h1>{tr("Current Situation")}</h1>
          <p className={styles.sceneTitle}>{s.title} {tr("— Turn")} {t.current_turn}</p>
          <div className={styles.sceneRule} aria-hidden="true"><span /></div>
          <p className={styles.story} data-reading data-reveal key={`${s.id}:${t.current_turn}`}>{t.current_situation}</p>
        </article>
        <div className={styles.brief}>{p.brief}</div>
        <div className={styles.move}>{p.action}</div>
        <aside className={styles.guidance}>{p.guidance}</aside>
        <div className={styles.coach}><Image className={styles.notebookArt} src="/illustrations/private-notebook.webp" width={56} height={56} sizes="(max-width: 480px) 32px, 56px" alt="" aria-hidden="true" />{p.coach}</div>
        <div className={styles.chat}><span className="section-label">{tr("THE SHARED SPACE")}</span>{p.chat}</div>
        <div className={styles.history}>{p.history}</div>
        <aside className={styles.context} aria-label={tr("Session context and utilities")}>
          <span className="section-label">{tr("YOUR PERSPECTIVE")}</span>
          <div className={styles.identity}><span aria-hidden="true">{p.profile.display_name.slice(0, 1).toUpperCase()}</span><div><h2>{p.profile.display_name}</h2><p>{role}</p></div></div>
          <p className={styles.score}>{tr("Peer score:")} {p.score} {tr("points")}</p>
          <section className={styles.contextGroup}><h3>{tr("In this room")}</h3>
            <ul>{p.members.map(m => <li key={m.user_id}><span aria-hidden="true" />{m.nickname || tr("Participant")}{m.user_id === p.profile.user_id && <small>{tr("You")}</small>}</li>)}</ul>
            {p.members.length === 1 && <p>{tr("Waiting for another participant. Share the invite code.")}</p>}
          </section>
          <section className={styles.contextGroup}><span className="section-label">{tr("THE SCENARIO")}</span><h3>{s.title}</h3><details><summary>{tr("Scenario context")}</summary><p>{s.context}</p><p>{s.conflict}</p></details></section>
          <div className={styles.contextGroup}>{p.profileForm}</div>
          <details className={styles.utilities}><summary>{tr("Room utilities")}</summary>{p.setup}</details>
          <div className={styles.utilityButtons}><button onClick={p.onRefresh}>{tr("Refresh status")}</button><button disabled={p.busy} data-tone="destructive" onClick={p.onLeave}>{tr("Leave room")}</button></div>
          <p className={styles.note}>{tr("A little space")}<br />{tr("for another perspective.")}</p>
        </aside>
        <div className={styles.peer}>{p.peer}</div>
      </main>
      <footer className={styles.footer}>{tr("Listen. Reflect.")} <em>{tr("Choose another way forward.")}</em></footer>
    </div>
  </div>;
}
