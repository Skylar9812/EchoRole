'use client';
import {useT} from '@/i18n/context';


import Image from 'next/image';
import {LanguageSelector} from '@/i18n/context';
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

/** Keep the artwork responsive, with a shallow frame on wide desktops. */
function Scene() {
 const tr=useT();

  return <div className={styles.scene} data-illustration-slot="hero" aria-hidden="true">
    <Image src="/illustrations/landing-hero.webp" alt="" aria-hidden="true" fill priority sizes="(max-width: 720px) 310px, (max-width: 1000px) 267px, (max-width: 1250px) calc(39vw - 31.2px), (max-width: 1536px) calc(46.8vw - 59.904px), 659px" className={styles.finalArt} />
    <span className={styles.sceneCaption}>{tr("A little space for a different perspective.")}</span>
  </div>;
}

export default function Landing({ profile, score, busy, loading = false, feedback, onProfile, onCreate, onJoin, onClearIdentity }: LandingProps) {
 const tr=useT();

  const unavailable = busy || loading;
  return <div data-echorole className={styles.page}>
    <a className={styles.skip} href="#character">{tr("Skip to your profile")}</a>
    <div className={styles.shell}>
      <header className={styles.header}>
        <Brand />
        <nav aria-label={tr("Main navigation")}><LanguageSelector />
          <a href="#how-it-works">{tr("How it works")}</a><a href="#rooms">{tr("Enter a room")}</a>
          <a className={styles.profileLink} href="#character" aria-label={profile ? tr('Your profile: {0}',profile.display_name) : tr("Build your character")}>{profile ? profile.display_name.slice(0, 1).toUpperCase() : <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="3.5" stroke="currentColor" strokeWidth="1.4" /><path d="M5 21v-2a7 7 0 0 1 14 0v2" stroke="currentColor" strokeWidth="1.4" /></svg>}</a>
        </nav>
      </header>

      <main className={styles.main} id="top">
        <section className={styles.hero} aria-labelledby="landing-title">
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>{tr("A LITTLE PRACTICE. A NEW PERSPECTIVE.")}</p>
            <h1 id="landing-title">{tr("Every conversation")}<br /><em>{tr("has another path.")}</em></h1>
            <p className={styles.intro}>{tr("Practice difficult conversations.")}<br className={styles.mobileBreak} /> {tr("Explore another way forward.")}</p>
            <ol className={styles.steps} id="how-it-works" aria-label={tr("How EchoRole works")}>
              <li><span>01</span><div>{tr("Create")}<small>{tr("Build your character")}</small></div></li>
              <li><span>02</span><div>{tr("Enter")}<small>{tr("Step into a scenario")}</small></div></li>
              <li><span>03</span><div>{tr("Practice")}<small>{tr("Find a new perspective")}</small></div></li>
            </ol>
          </div>
          <Scene />
        </section>

        {loading && <p className={styles.loading} role="status" data-loading>{tr("Getting your space ready. Recovering your profile…")}</p>}
        <Feedback>{feedback}</Feedback>

        <div className={styles.entry}>
          <section className={styles.character} id="character" tabIndex={-1} aria-labelledby="character-title">
            <div className={styles.panelHeading}><span className={styles.sectionNumber}>{tr("01 / YOU")}</span><h2 id="character-title">{tr("Build your character")}</h2></div>
            <div className={styles.characterBody}>
              <div className={styles.portraitColumn}>
                <div className={styles.portrait} data-illustration-slot="character" aria-hidden="true">
                  <Image src="/illustrations/character-profile.webp" alt="" aria-hidden="true" fill sizes="(max-width: 1250px) 112px, 146px" className={styles.finalArt} />
                </div>
                <p className={styles.handNote}>{tr("Same you,")}<br />{tr("more perspective.")}</p>
                <span className={styles.portraitCaption}>{tr("YOUR STORY STARTS HERE")}</span>
              </div>
              <form className={styles.profileForm} onSubmit={onProfile} key={profile?.user_id ?? 'new'} aria-label={tr("Your profile")}>
                <div className={styles.field}><label htmlFor="entry-name">{tr("Display name")}</label><input id="entry-name" name="name" autoComplete="nickname" placeholder={tr("What should we call you?")} required defaultValue={profile?.display_name} disabled={loading} /></div>
                <div className={styles.field}><label htmlFor="entry-mbti">{tr("MBTI")} <span>{tr("(optional)")}</span></label><input id="entry-mbti" name="mbti" placeholder={tr("e.g. INFJ")} defaultValue={profile?.mbti} disabled={loading} /></div>
                <div className={styles.field}><label htmlFor="entry-priorities">{tr("Communication / value priorities")}</label><textarea id="entry-priorities" name="priorities" placeholder={tr("What matters to you in a conversation?")} defaultValue={profile?.priorities} disabled={loading} rows={2} /></div>
                <div className={styles.profileActions}><button className={styles.saveButton} disabled={unavailable}>{profile ? tr("Save profile") : tr("Create profile")}<Arrow /></button><span>{profile ? tr("A little more you.") : tr("Start with what makes you, you.")}</span></div>
                {profile && <p className={styles.savedProfile}>{tr("Profile:")} {profile.display_name}<span>{tr("Peer score:")} {score} {tr("points")}</span></p>}
              </form>
            </div>
          </section>

          <section className={styles.rooms} id="rooms" aria-label={tr("Create or join a room")}>
            <h2 className={styles.srOnly}>{tr("Create or join a room")}</h2>
            <div className={styles.createPanel}>
              <Doorway />
              <div className={styles.roomCopy}><span className={styles.sectionNumber}>{tr("02 / A NEW BEGINNING")}</span><h2>{tr("Start a scenario")}</h2><p>{tr("A shared space. Two perspectives.")}<br />{tr("A conversation that could go differently.")}</p><button className={styles.primaryButton} onClick={onCreate} disabled={unavailable || !profile}>{tr("Create room")}<Arrow /></button></div>
              <p className={styles.roomNote}>{tr("A new")}<br />{tr("conversation")}<br />{tr("awaits.")}</p>
            </div>
            <div className={styles.joinPanel}>
              <div className={styles.invitation} data-illustration-slot="invitation" aria-hidden="true"><Image src="/illustrations/join-envelope.webp" alt="" aria-hidden="true" fill sizes="(max-width: 1250px) 80px, 102px" className={styles.finalArt} /></div>
              <div className={styles.joinCopy}><span className={styles.sectionNumber}>{tr("ALREADY INVITED?")}</span><h2>{tr("Join a room")}</h2><form onSubmit={onJoin}><label className={styles.srOnly} htmlFor="entry-code">{tr("Invite code")}</label><input id="entry-code" name="code" placeholder={tr("Invite code")} required autoComplete="off" spellCheck={false} disabled={loading} /><button className={styles.joinButton} disabled={unavailable || !profile}>{tr("Join room")}<Arrow /></button></form></div>
            </div>
            <p className={styles.roomHint}>{profile ? tr("Your profile is ready. Choose where your story begins.") : tr("Create your profile first, then create or join a room.")}</p>
          </section>
        </div>
      </main>
      <footer className={styles.footer}><p className={styles.footerNote}>{tr("Practice today.")}<br /><span>{tr("A kinder tomorrow.")}</span></p><div className={styles.footerRight}><span className={styles.footerWords}><span>{tr("PEOPLE")}</span><i /><span>{tr("CONVERSATIONS")}</span><i /><span>{tr("POSSIBILITIES")}</span></span><details className={styles.identity}><summary>{tr("Local identity")}</summary><p>{tr("Your profile is remembered in this browser.")}</p><button data-tone="destructive" onClick={onClearIdentity} disabled={unavailable}>{tr("Clear local identity")}</button></details></div></footer>
    </div>
  </div>;
}
