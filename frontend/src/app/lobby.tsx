'use client';

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
  const { profile, score, roomId, room, members, messages, catalog, category, scenarioId, chat, busy, pollError, feedback } = props;
  const [profileOpen, setProfileOpen] = useState(false);
  const selected = catalog.find(item => item.id === scenarioId);
  const options = catalog.filter(item => !category || item.category === category);
  const loading = !room;
  const unavailable = busy || loading || !!pollError;

  return <div data-echorole className={`${base.page} ${styles.page}`}>
    <a className={base.skip} href="#scenario-setup">Skip to scenario setup</a>
    <div className={base.shell}>
      <header className={`${base.header} ${styles.header}`} id="top">
        <Brand />
        <div className={styles.roomIdentity} aria-label={`Room ${roomId}`}>
          <span className={styles.eyebrow}>ROOM CODE</span>
          <strong>{room?.invite_code ?? 'Loading…'}</strong>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.roomState}>Lobby <i /> {members ? `${members.length} participants` : 'Connecting'}</span>
          <a className={styles.profileLink} href="#lobby-profile" onClick={() => setProfileOpen(true)} aria-label={`Edit profile: ${profile.display_name}`}>
            <span className={styles.avatar} aria-hidden="true">{profile.display_name.slice(0, 1).toUpperCase()}</span><span>{profile.display_name}</span>
          </a>
        </div>
      </header>

      <main className={`${base.main} ${styles.main}`}>
        <div className={styles.introduction}>
          <div><p className={styles.eyebrow}>THE PREPARATION ROOM</p><p className={styles.welcome}>A moment before <em>the conversation.</em></p></div>
          <p>Gather here. Choose a scenario.<br />Step into another point of view.</p>
        </div>
        <Feedback>{feedback}</Feedback>
        {pollError && <ConnectionNotice error={pollError} onRetry={props.onRefresh} />}
        {loading && !pollError && <p className={styles.loading} role="status" data-loading>Opening your preparation room. Loading room…</p>}

        <div className={styles.layout}>
          <section className={styles.scenarioSection} id="scenario-setup" tabIndex={-1} aria-label="Scenario setup">
            <div className={styles.selectionHeading}><span className={styles.eyebrow}>01 / CHOOSE YOUR SCENARIO</span><span className={styles.selectionHint}>A starting point, not a script.</span></div>
            <div className={styles.selectors}>
              <div><label htmlFor="lobby-category">Category</label><select id="lobby-category" value={category} onChange={event => props.onCategory(event.target.value)} disabled={busy || loading}><option value="">All categories</option>{[...new Set(catalog.map(item => item.category))].map(item => <option key={item}>{item}</option>)}</select></div>
              <div><label htmlFor="lobby-scenario">Scenario</label><select id="lobby-scenario" value={scenarioId} onChange={event => props.onScenario(event.target.value)} disabled={busy || loading}><option value="">Choose a scenario</option>{options.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></div>
            </div>

            <article className={styles.scenarioPaper} aria-labelledby="scenario-title" aria-busy={loading}>
              <div className={styles.scenarioTop}>
                <div><span className={styles.eyebrow}>SCENARIO</span><h1 id="scenario-title">{selected?.title ?? 'Which conversation will you enter?'}</h1>{selected && <p className={styles.category}>{selected.category}</p>}</div>
                <div className={styles.doorwayArt} aria-hidden="true"><Doorway preview={!selected} /></div>
              </div>
              {selected ? <div className={styles.scenarioText} data-reveal key={selected.id}>
                <section aria-labelledby="context-title"><h2 id="context-title">Context</h2><p>{selected.context}</p></section>
                <section className={styles.tension} aria-labelledby="tension-title"><h2 id="tension-title">Core tension</h2><p>{selected.conflict}</p></section>
                <section aria-labelledby="opening-title"><h2 id="opening-title">Opening situation</h2><p>{selected.opening_situation}</p></section>
              </div> : <div className={styles.emptyScenario}><p>{loading ? 'Your room is opening. You can choose your scenario in a moment.' : !catalog.length ? 'No scenarios available.' : 'Choose a scenario above to explore its context, the tension between two people, and the moment where your story begins.'}</p><p className={styles.editorialNote}>There is more than one way forward.</p></div>}
              <div className={styles.beginning}>
                <div><span className={styles.eyebrow}>WHAT HAPPENS NEXT</span><p>Your roles are assigned when the session begins.<br />Then, read your private brief and take your first turn.</p></div>
                <button className={base.primaryButton} onClick={props.onStart} disabled={unavailable || !selected}>Start session<Arrow /></button>
              </div>
            </article>
          </section>

          <aside className={styles.sidebar}>
            <section className={styles.participants} aria-labelledby="participants-title">
              <div className={styles.sideHeading}><h2 id="participants-title">In this room</h2><span>{members ? `${members.length} / 2` : '— / 2'}</span></div>
              <ul className={styles.memberList}>
                {members?.map(member => <li key={member.user_id}><span className={styles.memberAvatar} aria-hidden="true">{(member.nickname ?? 'Participant').slice(0, 1).toUpperCase()}</span><div><strong>{member.nickname ?? 'Participant'}</strong>{member.user_id === profile.user_id && <span className={styles.you}>You</span>}<p><i /> In the room · role not assigned yet</p></div></li>)}
                {!members && <li className={styles.waitingSeat}><span className={styles.emptyAvatar} aria-hidden="true">—</span><p>Loading participants…</p></li>}
                {members?.length === 1 && <li className={styles.waitingSeat}><span className={styles.emptyAvatar} aria-hidden="true">+</span><div><strong>A place for your partner</strong><p>Waiting for another participant.</p></div></li>}
                {members?.length === 0 && <li>No participants to display. Refresh room status.</li>}
              </ul>
              <p className={styles.memberHint}>{members?.length === 1 ? 'Share the invite code so your partner can join you.' : 'Roles will be assigned when the scenario starts.'}</p>
            </section>

            <section className={styles.chatSection} aria-labelledby="room-chat-title">
              <div className={styles.sideHeading}><h2 id="room-chat-title">Room conversation</h2><span className={styles.sharedLabel}>SHARED</span></div>
              <p className={styles.chatHint}>Visible to everyone in this room.</p>
              <div className={styles.chatHistory} role="region" tabIndex={0} aria-label="Shared room messages">
                {messages?.length ? <ol>{messages.map(message => <li key={message.id} data-reveal><strong>{message.username ?? 'Participant'}</strong><p>{message.content}</p></li>)}</ol> : <p className={styles.chatEmpty}>{loading ? 'Loading shared messages…' : 'Say hello, or share a thought before you begin.'}</p>}
              </div>
              <form onSubmit={event => { event.preventDefault(); props.onSendChat(); }}>
                <label htmlFor="lobby-chat">Shared message</label><textarea id="lobby-chat" value={chat} onChange={event => props.onChat(event.target.value)} required rows={2} placeholder="A few words to your partner…" disabled={loading} />
                <button className={base.saveButton} disabled={unavailable || !chat.trim()}>Send message<Arrow /></button>
              </form>
            </section>

            <details className={styles.profile} id="lobby-profile" open={profileOpen} onToggle={event => setProfileOpen(event.currentTarget.open)}>
              <summary>Your profile <span>Edit</span></summary>
              <p className={styles.score}>Peer score: {score} points</p>
              <form onSubmit={props.onProfile} key={profile.user_id}>
                <label htmlFor="lobby-name">Display name</label><input id="lobby-name" name="name" required defaultValue={profile.display_name} />
                <label htmlFor="lobby-mbti">MBTI (optional)</label><input id="lobby-mbti" name="mbti" defaultValue={profile.mbti} />
                <label htmlFor="lobby-priorities">Communication / value priorities</label><textarea id="lobby-priorities" name="priorities" defaultValue={profile.priorities} rows={2} />
                <button className={base.saveButton} disabled={busy}>Save profile<Arrow /></button>
              </form>
              <details className={styles.identity}><summary>Local identity</summary><button disabled={busy} data-tone="destructive" onClick={props.onClearIdentity}>Clear local identity</button></details>
            </details>
          </aside>
        </div>
        <footer className={styles.footer}><p>Take a breath. <em>There’s room for another perspective.</em></p><div><button className={styles.quietButton} onClick={props.onRefresh}>Refresh status</button><button className={styles.quietButton} data-tone="destructive" onClick={props.onLeave} disabled={busy}>Leave room</button></div></footer>
      </main>
    </div>
  </div>;
}
