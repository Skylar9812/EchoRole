'use client';

import Image from 'next/image';
import { Feedback } from './ui-feedback';

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

/** Final artwork stays inside the approved hero's reserved dimensions. */
function Scene() {
  return <div className={styles.scene} data-illustration-slot="hero" aria-hidden="true">
    <Image src="/illustrations/landing-hero.webp" alt="" aria-hidden="true" fill priority sizes="(max-width: 720px) 310px, (max-width: 1000px) 267px, (max-width: 1250px) 391px, (min-width: 1450px) 503px, 465px" className={styles.finalArt} />
    <span className={styles.sceneCaption}>A little space for a different perspective.</span>
  </div>;
}

export default function Landing({ profile, score, busy, loading = false, feedback, onProfile, onCreate, onJoin, onClearIdentity }: LandingProps) {
  const unavailable = busy || loading;
  return <div data-echorole className={styles.page}>
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

        {loading && <p className={styles.loading} role="status" data-loading>Getting your space ready. Recovering your profile…</p>}
        <Feedback>{feedback}</Feedback>

        <div className={styles.entry}>
          <section className={styles.character} id="character" tabIndex={-1} aria-labelledby="character-title">
            <div className={styles.panelHeading}><span className={styles.sectionNumber}>01 / YOU</span><h2 id="character-title">Build your character</h2></div>
            <div className={styles.characterBody}>
              <div className={styles.portraitColumn}>
                <div className={styles.portrait} data-illustration-slot="character" aria-hidden="true">
                  <Image src="/illustrations/character-profile.webp" alt="" aria-hidden="true" fill sizes="(max-width: 1250px) 112px, 146px" className={styles.finalArt} />
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
              <div className={styles.invitation} data-illustration-slot="invitation" aria-hidden="true"><Image src="/illustrations/join-envelope.webp" alt="" aria-hidden="true" fill sizes="(max-width: 1250px) 80px, 102px" className={styles.finalArt} /></div>
              <div className={styles.joinCopy}><span className={styles.sectionNumber}>ALREADY INVITED?</span><h2>Join a room</h2><form onSubmit={onJoin}><label className={styles.srOnly} htmlFor="entry-code">Invite code</label><input id="entry-code" name="code" placeholder="Invite code" required autoComplete="off" spellCheck={false} disabled={loading} /><button className={styles.joinButton} disabled={unavailable || !profile}>Join room<Arrow /></button></form></div>
            </div>
            <p className={styles.roomHint}>{profile ? 'Your profile is ready. Choose where your story begins.' : 'Create your profile first, then create or join a room.'}</p>
          </section>
        </div>
      </main>
      <footer className={styles.footer}><p className={styles.footerNote}>Practice today.<br /><span>A kinder tomorrow.</span></p><div className={styles.footerRight}><span className={styles.footerWords}><span>PEOPLE</span><i /><span>CONVERSATIONS</span><i /><span>POSSIBILITIES</span></span><details className={styles.identity}><summary>Local identity</summary><p>Your profile is remembered in this browser.</p><button data-tone="destructive" onClick={onClearIdentity} disabled={unavailable}>Clear local identity</button></details></div></footer>
    </div>
  </div>;
}
