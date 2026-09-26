'use client';
import {useT} from '@/i18n/context';


import SharedChat from './shared-chat';
import { Feedback, ConnectionNotice } from './ui-feedback';

import { useState, type FormEvent, type ReactNode } from 'react';
import type { Member, Profile, Room, Scenario, SharedMessage } from '@/lib/contracts';
import { Brand, Arrow, Doorway } from './editorial';
import base from './landing.module.css';
import styles from './lobby.module.css';

type LobbyProps = {
  profile: Profile;
  score: number;
  roomId: number;
  room?: Room;
  members?: Member[];
  messages?: SharedMessage[];
  catalog: Scenario[];
  category: string;
  scenarioId: string;
  chat: string;
  busy: boolean;
  pollError: string;
  feedback: ReactNode;
  onCategory: (value: string) => void;
  onScenario: (value: string) => void;
  onChat: (value: string) => void;
  onSendChat: () => void;
  onStart: () => void;
  onRefresh: () => void;
  onLeave: () => void;
  onProfile: (event: FormEvent<HTMLFormElement>) => void;
  onClearIdentity: () => void;
};

export default function Lobby(props: LobbyProps) {
 const tr=useT();

  const { profile, score, roomId, room, members, messages, catalog, category, scenarioId, chat, busy, pollError, feedback } = props;
  const [profileOpen, setProfileOpen] = useState(false);
  const selected = catalog.find(item => item.id === scenarioId);
  const options = catalog.filter(item => !category || item.category === category);
  const loading = !room;
  const unavailable = busy || loading || !!pollError;

  return <div data-echorole className={`${base.page} ${styles.page}`}>
    <a className={base.skip} href="#scenario-setup">{tr("Skip to scenario setup")}</a>
    <div className={base.shell}>
      <header className={`${base.header} ${styles.header}`} id="top">
        <Brand /><span className="room-language" title={tr("Room language is locked.")}>{room?.language}</span>
        <div className={styles.roomIdentity} aria-label={tr("Room {0}",roomId)}>
          <span className={styles.eyebrow}>{tr("ROOM CODE")}</span>
          <strong>{room?.invite_code ?? tr('Loading…')}</strong>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.roomState}>{tr("Lobby")} <i /> {members ? tr('{0} participants',members.length) : tr("Connecting")}</span>
          <a className={styles.profileLink} href="#lobby-profile" onClick={() => setProfileOpen(true)} aria-label={tr("Edit profile: {0}",profile.display_name)}>
            <span className={styles.avatar} aria-hidden="true">{profile.display_name.slice(0, 1).toUpperCase()}</span><span>{profile.display_name}</span>
          </a>
        </div>
      </header>

      <main className={`${base.main} ${styles.main}`}>
        <div className={styles.introduction}>
          <div><p className={styles.eyebrow}>{tr("THE PREPARATION ROOM")}</p><p className={styles.welcome}>{tr("A moment before")} <em>{tr("the conversation.")}</em></p></div>
          <p>{tr("Gather here. Choose a scenario.")}<br />{tr("Step into another point of view.")}</p>
        </div>
        <Feedback>{feedback}</Feedback>
        {pollError && <ConnectionNotice error={pollError} onRetry={props.onRefresh} />}
        {loading && !pollError && <p className={styles.loading} role="status" data-loading>{tr("Opening your preparation room. Loading room…")}</p>}

        <div className={styles.layout}>
          <section className={styles.scenarioSection} id="scenario-setup" tabIndex={-1} aria-label={tr("Scenario setup")}>
            <div className={styles.selectionHeading}><span className={styles.eyebrow}>{tr("01 / CHOOSE YOUR SCENARIO")}</span><span className={styles.selectionHint}>{tr("A starting point, not a script.")}</span></div>
            <div className={styles.selectors}>
              <div><label htmlFor="lobby-category">{tr("Category")}</label><select id="lobby-category" value={category} onChange={event => props.onCategory(event.target.value)} disabled={busy || loading}><option value="">{tr("All categories")}</option>{[...new Set(catalog.map(item => item.category))].map(item => <option key={item}>{item}</option>)}</select></div>
              <div><label htmlFor="lobby-scenario">{tr("Scenario")}</label><select id="lobby-scenario" value={scenarioId} onChange={event => props.onScenario(event.target.value)} disabled={busy || loading}><option value="">{tr("Choose a scenario")}</option>{options.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></div>
            </div>

            <article className={styles.scenarioPaper} aria-labelledby="scenario-title" aria-busy={loading}>
              <div className={styles.scenarioTop}>
                <div><span className={styles.eyebrow}>{tr("SCENARIO")}</span><h1 id="scenario-title">{selected?.title ?? tr("Which conversation will you enter?")}</h1>{selected && <p className={styles.category}>{selected.category}</p>}</div>
                <div className={styles.doorwayArt} aria-hidden="true"><Doorway preview={!selected} /></div>
              </div>
              {selected ? <div className={styles.scenarioText} data-reveal key={selected.id}>
                <section aria-labelledby="context-title"><h2 id="context-title">{tr("Context")}</h2><p>{selected.context}</p></section>
                <section className={styles.tension} aria-labelledby="tension-title"><h2 id="tension-title">{tr("Core tension")}</h2><p>{selected.conflict}</p></section>
                <section aria-labelledby="opening-title"><h2 id="opening-title">{tr("Opening situation")}</h2><p>{selected.opening_situation}</p></section>
              </div> : <div className={styles.emptyScenario}><p>{loading ? tr("Your room is opening. You can choose your scenario in a moment.") : !catalog.length ? tr("No scenarios available.") : tr("Choose a scenario above to explore its context, the tension between two people, and the moment where your story begins.")}</p><p className={styles.editorialNote}>{tr("There is more than one way forward.")}</p></div>}
              <div className={styles.beginning}>
                <div><span className={styles.eyebrow}>{tr("WHAT HAPPENS NEXT")}</span><p>{tr("Your roles are assigned when the session begins.")}<br />{tr("Then, read your private brief and take your first turn.")}</p></div>
                <button className={base.primaryButton} onClick={props.onStart} disabled={unavailable || !selected}>{tr("Start session")}<Arrow /></button>
              </div>
            </article>
          </section>

          <aside className={styles.sidebar}>
            <section className={styles.participants} aria-labelledby="participants-title">
              <div className={styles.sideHeading}><h2 id="participants-title">{tr("In this room")}</h2><span>{members ? `${members.length} / 2` : '— / 2'}</span></div>
              <ul className={styles.memberList}>
                {members?.map(member => <li key={member.user_id}><span className={styles.memberAvatar} aria-hidden="true">{(member.nickname ?? tr("Participant")).slice(0, 1).toUpperCase()}</span><div><strong>{member.nickname ?? tr("Participant")}</strong>{member.user_id === profile.user_id && <span className={styles.you}>{tr("You")}</span>}<p><i /> {tr("In the room · role not assigned yet")}</p></div></li>)}
                {!members && <li className={styles.waitingSeat}><span className={styles.emptyAvatar} aria-hidden="true">—</span><p>{tr("Loading participants…")}</p></li>}
                {members?.length === 1 && <li className={styles.waitingSeat}><span className={styles.emptyAvatar} aria-hidden="true">+</span><div><strong>{tr("A place for your partner")}</strong><p>{tr("Waiting for another participant.")}</p></div></li>}
                {members?.length === 0 && <li>{tr("No participants to display. Refresh room status.")}</li>}
              </ul>
              <p className={styles.memberHint}>{members?.length === 1 ? tr("Share the invite code so your partner can join you.") : tr("Roles will be assigned when the scenario starts.")}</p>
            </section>

            <div className={styles.chatSection}><SharedChat userId={profile.user_id} messages={messages ?? []} value={chat} onChange={props.onChat} onSend={props.onSendChat} busy={busy} disabled={unavailable} /></div>

            <details className={styles.profile} id="lobby-profile" open={profileOpen} onToggle={event => setProfileOpen(event.currentTarget.open)}>
              <summary>{tr("Your profile")} <span>{tr("Edit")}</span></summary>
              <p className={styles.score}>{tr("Peer score:")} {score} {tr("points")}</p>
              <form onSubmit={props.onProfile} key={profile.user_id}>
                <label htmlFor="lobby-name">{tr("Display name")}</label><input id="lobby-name" name="name" required defaultValue={profile.display_name} />
                <label htmlFor="lobby-mbti">{tr("MBTI (optional)")}</label><input id="lobby-mbti" name="mbti" defaultValue={profile.mbti} />
                <label htmlFor="lobby-priorities">{tr("Communication / value priorities")}</label><textarea id="lobby-priorities" name="priorities" defaultValue={profile.priorities} rows={2} />
                <button className={base.saveButton} disabled={busy}>{tr("Save profile")}<Arrow /></button>
              </form>
              <details className={styles.identity}><summary>{tr("Local identity")}</summary><button disabled={busy} data-tone="destructive" onClick={props.onClearIdentity}>{tr("Clear local identity")}</button></details>
            </details>
          </aside>
        </div>
        <footer className={styles.footer}><p>{tr("Take a breath.")} <em>{tr("There’s room for another perspective.")}</em></p><div><button className={styles.quietButton} onClick={props.onRefresh}>{tr("Refresh status")}</button><button className={styles.quietButton} data-tone="destructive" onClick={props.onLeave} disabled={busy}>{tr("Leave room")}</button></div></footer>
      </main>
    </div>
  </div>;
}
