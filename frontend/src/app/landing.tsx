'use client';

import type { FormEvent, ReactNode } from 'react';
import type { Profile } from '@/lib/contracts';
import styles from './landing.module.css';
import { Brand, Arrow, Doorway } from './editorial';

type LandingProps = {
  profile: Profile | null;
  score: number;
  busy: boolean;
  loading?: boolean;
  feedback?: ReactNode;
  onProfile: (event: FormEvent<HTMLFormElement>) => void;
  onCreate: () => void;
  onJoin: (event: FormEvent<HTMLFormElement>) => void;
  onClearIdentity: () => void;
};

/** Temporary, code-native paper composition. Replace slots with final art later. */
function Scene() {
  return <div className={styles.scene} data-illustration-slot="hero" aria-hidden="true">
    <div className={styles.archFrame}><div className={styles.arch}>
      <span className={styles.sun} /><span className={styles.farHill} /><span className={styles.nearHill} /><span className={styles.path} />
    </div></div>
    <div className={styles.sceneNote}>Different conversations.<br />A kinder you.<span /></div>
    <svg className={styles.branch} viewBox="0 0 160 260" fill="none">
      <path d="M80 248C83 155 45 90 98 15M77 186C99 159 124 130 132 95M72 143C44 129 27 102 22 80" stroke="#697d60" strokeWidth="2" />
      <g fill="#87967a"><ellipse cx="93" cy="40" rx="12" ry="28" transform="rotate(30 93 40)" /><ellipse cx="66" cy="70" rx="12" ry="26" transform="rotate(-28 66 70)" /><ellipse cx="82" cy="106" rx="13" ry="27" transform="rotate(41 82 106)" /><ellipse cx="46" cy="111" rx="11" ry="25" transform="rotate(-47 46 111)" /><ellipse cx="123" cy="125" rx="11" ry="24" transform="rotate(27 123 125)" /><ellipse cx="102" cy="155" rx="10" ry="24" transform="rotate(54 102 155)" /><ellipse cx="71" cy="178" rx="11" ry="25" transform="rotate(-22 71 178)" /></g>
    </svg>
    <div className={styles.vase} /><div className={styles.table} />
    <div className={styles.books}><span /><span /><span /></div><div className={styles.cup} />
    <span className={styles.sceneCaption}>A little space for a different perspective.</span>
  </div>;
}

export default function Landing({ profile, score, busy, loading = false, feedback, onProfile, onCreate, onJoin, onClearIdentity }: LandingProps) {
  const unavailable = busy || loading;
  return <div className={styles.page}>
    <a className={styles.skip} href="#character">Skip to your profile</a>
    <div className={styles.shell}>
      <header className={styles.header}>
        <Brand />
        <nav aria-label="Main navigation">
          <a href="#how-it-works">How it works</a><a href="#rooms">Enter a room</a>
          <a className={styles.profileLink} href="#character" aria-label={profile ? `Your profile: ${profile.display_name}` : 'Build your character'}>{profile ? profile.display_name.slice(0, 1).toUpperCase() : <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="3.5" stroke="currentColor" strokeWidth="1.4" /><path d="M5 21v-2a7 7 0 0 1 14 0v2" stroke="currentColor" strokeWidth="1.4" /></svg>}</a>
        </nav>
      </header>

      <main className={styles.main} id="top">
        <section className={styles.hero} aria-labelledby="landing-title">
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>A LITTLE PRACTICE. A NEW PERSPECTIVE.</p>
            <h1 id="landing-title">Every conversation<br /><em>has another path.</em></h1>
            <p className={styles.intro}>Practice difficult conversations.<br className={styles.mobileBreak} /> Explore another way forward.</p>
            <ol className={styles.steps} id="how-it-works" aria-label="How EchoRole works">
              <li><span>01</span><div>Create<small>Build your character</small></div></li>
              <li><span>02</span><div>Enter<small>Step into a scenario</small></div></li>
              <li><span>03</span><div>Practice<small>Find a new perspective</small></div></li>
            </ol>
          </div>
          <Scene />
        </section>

        {loading && <p className={styles.loading} role="status">Getting your space ready. Recovering your profile…</p>}
        <div className={styles.feedback} aria-live="polite">{feedback}</div>

        <div className={styles.entry}>
          <section className={styles.character} id="character" aria-labelledby="character-title">
            <div className={styles.panelHeading}><span className={styles.sectionNumber}>01 / YOU</span><h2 id="character-title">Build your character</h2></div>
            <div className={styles.characterBody}>
              <div className={styles.portraitColumn}>
                <div className={styles.portrait} data-illustration-slot="character" aria-hidden="true">
                  <svg viewBox="0 0 180 200" fill="none"><path d="M29 191c3-48 23-68 61-68s59 20 62 68" fill="#83937a" /><path d="M61 126c-15-15-18-38-10-62 7-26 24-39 46-35 26 5 39 36 27 66-3 12-3 26 7 41-29 9-45 9-70-10Z" fill="#666653" /><path d="M102 60c-4 24-24 28-36 31 0 20 10 35 24 35 14 0 29-19 29-40-8-4-11-12-17-26Z" fill="#d9c2a6" /><path d="M35 165c20 9 35 18 47 34M127 146l-14 53" stroke="#65785e" strokeWidth="1.5" /></svg>
                </div>
                <p className={styles.handNote}>Same you,<br />more perspective.</p>
                <span className={styles.portraitCaption}>YOUR STORY STARTS HERE</span>
              </div>
              <form className={styles.profileForm} onSubmit={onProfile} key={profile?.user_id ?? 'new'} aria-label="Your profile">
                <div className={styles.field}><label htmlFor="entry-name">Display name</label><input id="entry-name" name="name" autoComplete="nickname" placeholder="What should we call you?" required defaultValue={profile?.display_name} disabled={loading} /></div>
                <div className={styles.field}><label htmlFor="entry-mbti">MBTI <span>(optional)</span></label><input id="entry-mbti" name="mbti" placeholder="e.g. INFJ" defaultValue={profile?.mbti} disabled={loading} /></div>
                <div className={styles.field}><label htmlFor="entry-priorities">Communication / value priorities</label><textarea id="entry-priorities" name="priorities" placeholder="What matters to you in a conversation?" defaultValue={profile?.priorities} disabled={loading} rows={2} /></div>
                <div className={styles.profileActions}><button className={styles.saveButton} disabled={unavailable}>{profile ? 'Save profile' : 'Create profile'}<Arrow /></button><span>{profile ? 'A little more you.' : 'Start with what makes you, you.'}</span></div>
                {profile && <p className={styles.savedProfile}>Profile: {profile.display_name}<span>Peer score: {score} points</span></p>}
              </form>
            </div>
          </section>

          <section className={styles.rooms} id="rooms" aria-label="Create or join a room">
            <h2 className={styles.srOnly}>Create or join a room</h2>
            <div className={styles.createPanel}>
              <Doorway />
              <div className={styles.roomCopy}><span className={styles.sectionNumber}>02 / A NEW BEGINNING</span><h2>Start a scenario</h2><p>A shared space. Two perspectives.<br />A conversation that could go differently.</p><button className={styles.primaryButton} onClick={onCreate} disabled={unavailable || !profile}>Create room<Arrow /></button></div>
              <p className={styles.roomNote}>A new<br />conversation<br />awaits.</p>
            </div>
            <div className={styles.joinPanel}>
              <div className={styles.invitation} data-illustration-slot="invitation" aria-hidden="true"><svg width="54" height="42" viewBox="0 0 54 42" fill="none"><rect x="2" y="2" width="50" height="38" rx="2" stroke="currentColor" /><path d="m3 4 24 19L51 4M3 39l17-16m31 16L34 23" stroke="currentColor" /></svg></div>
              <div className={styles.joinCopy}><span className={styles.sectionNumber}>ALREADY INVITED?</span><h2>Join a room</h2><form onSubmit={onJoin}><label className={styles.srOnly} htmlFor="entry-code">Invite code</label><input id="entry-code" name="code" placeholder="Enter your invite code" required autoComplete="off" spellCheck={false} disabled={loading} /><button className={styles.joinButton} disabled={unavailable || !profile}>Join room<Arrow /></button></form></div>
            </div>
            <p className={styles.roomHint}>{profile ? 'Your profile is ready. Choose where your story begins.' : 'Create your profile first, then create or join a room.'}</p>
          </section>
        </div>
      </main>
      <footer className={styles.footer}><p className={styles.footerNote}>Practice today.<br /><span>A kinder tomorrow.</span></p><div className={styles.footerRight}><span className={styles.footerWords}>PEOPLE <i /> CONVERSATIONS <i /> POSSIBILITIES</span><details className={styles.identity}><summary>Local identity</summary><p>Your profile is remembered in this browser.</p><button onClick={onClearIdentity} disabled={unavailable}>Clear local identity</button></details></div></footer>
    </div>
  </div>;
}
