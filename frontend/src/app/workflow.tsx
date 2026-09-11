'use client';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import Landing from './landing';
import Lobby from './lobby';
import ActiveSession from './active-session';
import { api, ApiError, pending } from '@/lib/client';
import type { Profile, ProfileInput, Room, Member, Scenario, Session, SharedMessage, PrivateState, CoachMessage, CoachResult, Suggestion, TurnStatus, ProgressionEntry, ChatSend, CoachSend, ActionSend, PeerFeedbackState, PeerFeedbackSend } from '@/lib/contracts';

type Snapshot = { feedback?: PeerFeedbackState; total_points: number; room: Room; members: Member[]; session: Session | null; chat: SharedMessage[]; private?: PrivateState; coach?: CoachMessage[]; requests?: CoachResult[]; suggestion?: Suggestion; turn?: TurnStatus; history?: ProgressionEntry[] };
function Text({children}: {children: string}) { return <p className="text">{children}</p>; }
function Recovery({busy, recover}: {busy: boolean; recover: () => void}) {
  const [ack, setAck] = useState(false);
  return <div role="alert"><p>Generation outcome is uncertain. An earlier AI request may have run. Recovery can repeat external AI work; it will not advance the database turn twice.</p><label><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} /> I acknowledge that recovery may repeat the AI request.</label><button disabled={!ack || busy} onClick={recover}>Recover generation</button></div>;
}
export default function EchoRole() {
  const [staleIdentity, setStaleIdentity] = useState(false);
  const [score, setScore] = useState(0);
  const [profile, setProfile] = useState<Profile | null>(null), [boot, setBoot] = useState(true);
  const [roomId, setRoomId] = useState<number | null>(null), [data, setData] = useState<Snapshot | null>(null);
  const [catalog, setCatalog] = useState<Scenario[]>([]), [category, setCategory] = useState(''), [scenario, setScenario] = useState('');
  const [error, setError] = useState(''), [pollError, setPollError] = useState(''), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [chat, setChat] = useState(''), [coach, setCoach] = useState(''), [action, setAction] = useState('');
  const epoch = useRef(0), locked = useRef(false), polling = useRef(false);
  const clear = useCallback(() => { epoch.current++; setData(null); setChat(''); setCoach(''); setAction(''); }, []);
  const selectRoom = useCallback((id: number | null) => { clear(); setRoomId(id); if (id) sessionStorage.setItem('echorole-room', String(id)); else sessionStorage.removeItem('echorole-room'); }, [clear]);
  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) { clear(); setProfile(null); setScore(0); setRoomId(null); setStaleIdentity(true); sessionStorage.removeItem('echorole-room'); setError('This local profile is no longer available. Start with a new profile to continue.'); }
    else setError(`${e instanceof ApiError && e.status === 409 ? 'State changed or stale turn. Refresh status before retrying. ' : ''}${e instanceof Error ? e.message : 'Request failed'}`);
  }, [clear]);
  const refresh = useCallback(async () => {
    if (!roomId || !profile || polling.current) return;
    polling.current = true; const version = epoch.current;
    try {
      const [room, members, session, messages, points] = await Promise.all([api.room(roomId), api.members(roomId), api.session(roomId), api.chat(roomId), api.score()]);
      const next: Snapshot = {room, members, session, chat: messages, total_points: points.total_points};
      if (session) {
        const [privateState, coachMessages, requests, suggestion, turn, history, feedback] = await Promise.all([api.private(session.id), api.coach(session.id), api.requests(session.id), api.suggestion(session.id), api.turn(session.id), api.history(session.id), api.feedback(session.id)]);
        // A turn can advance between reads. Publish only a consistent projection.
        if (turn.current_turn !== session.current_turn || privateState.turn_index !== turn.current_turn || suggestion.turn_index !== turn.current_turn) return;
        Object.assign(next, {private: privateState, coach: coachMessages, requests, suggestion, turn, history, feedback});
      }
      if (epoch.current === version) { setData(previous => { if (previous?.session?.id !== session?.id || previous?.turn?.current_turn !== next.turn?.current_turn) { setAction(''); setNotice(previous?.session ? 'Session updated. Review your current brief before acting.' : ''); } return next; }); setScore(points.total_points); setPollError(''); }
    } catch (e) { if (version === epoch.current) { if (e instanceof ApiError && (e.status === 401 || e.status === 403)) { clear(); fail(e); } setPollError(e instanceof Error ? e.message : 'Refresh failed'); } }
    finally { polling.current = false; }
  }, [roomId, profile, clear, fail]);
  useEffect(() => { let live = true; Promise.all([api.me().catch(e => { if (e instanceof ApiError && e.status === 401) { if (e.code === 'stale_identity') fail(e); return null; } throw e; }), api.scenarios()]).then(([p, c]) => { if (!live) return; setProfile(p); setCatalog(c); if (p) void api.score().then(x => { if (live) setScore(x.total_points); }).catch(fail); if (p) { const id = Number(sessionStorage.getItem('echorole-room')); if (id > 0) setRoomId(id); } }).catch(fail).finally(() => { if (live) setBoot(false); }); return () => { live = false; }; }, [fail]);
  useEffect(() => { let live = true; let timer: ReturnType<typeof setTimeout>; const tick = async () => { if (!document.hidden) await refresh(); if (live) timer = setTimeout(tick, 2500); }; void tick(); const visible = () => { if (!document.hidden) void refresh(); }; document.addEventListener('visibilitychange', visible); window.addEventListener('online', visible); return () => { live = false; clearTimeout(timer); document.removeEventListener('visibilitychange', visible); window.removeEventListener('online', visible); }; }, [refresh]);
  async function run(work: () => Promise<unknown>) { if (locked.current) return; locked.current = true; setBusy(true); setError(''); try { await work(); await refresh(); } catch (e) { fail(e); } finally { locked.current = false; setBusy(false); } }
  function profileForm(e: FormEvent<HTMLFormElement>) { e.preventDefault(); const f = new FormData(e.currentTarget); const input: ProfileInput = {display_name: String(f.get('name')).trim(), mbti: String(f.get('mbti')), priorities: String(f.get('priorities'))}; void run(async () => { setProfile(await api.profile(input, !!profile)); setScore((await api.score()).total_points); }); }
  async function send(kind: 'chat' | 'coach' | 'action') {
    if (!profile || !roomId) return; const sid = data?.session?.id, turn = data?.turn?.current_turn;
    const key = `echorole:${profile.user_id}:${kind}:${kind === 'chat' ? roomId : `${sid}:${turn}`}`;
    try {
    if (kind === 'chat') { const body = pending(key, {request_id: crypto.randomUUID(), content: chat.trim()}); await api.sendChat(roomId, body); setChat(''); }
    if (kind === 'coach' && sid && turn) { const body = pending(key, {request_id: crypto.randomUUID(), content: coach.trim(), turn_index: turn}); await api.sendCoach(sid, body); setCoach(''); }
    if (kind === 'action' && sid && turn) { const body = pending(key, {turn_index: turn, action_text: action.trim()}); await api.action(sid, body); setAction(''); }
    sessionStorage.removeItem(key);
    } catch (e) { if (e instanceof ApiError && e.status === 422) sessionStorage.removeItem(key); throw e; }
  }
  const retries = profile ? Object.keys(sessionStorage).filter(k => k.startsWith(`echorole:${profile.user_id}:`) && /:(chat|coach|action|setup|feedback):/.test(k)) : [];
  async function retrySaved(key: string) {
    const raw = sessionStorage.getItem(key); if (!raw) return;
    const parts = key.split(':'); const kind = parts[2], id = Number(parts[3]);
    if (kind === 'setup') { const body = JSON.parse(raw) as {scenario_id: string; expected_session_id?: number}; await api.start(id, body.scenario_id, body.expected_session_id); }
    if (kind === 'feedback') await api.sendFeedback(id, JSON.parse(raw) as PeerFeedbackSend);
    if (kind === 'chat') await api.sendChat(id, JSON.parse(raw) as ChatSend);
    if (kind === 'coach') await api.sendCoach(id, JSON.parse(raw) as CoachSend);
    if (kind === 'action') await api.action(id, JSON.parse(raw) as ActionSend);
    sessionStorage.removeItem(key);
  }
  const feedback = <>
    {error && <div role="alert"><p>{error}</p>{staleIdentity ? <button disabled={busy} onClick={clearIdentity}>Start with a new profile</button> : <button disabled={busy} onClick={() => void run(async () => { await refresh(); if (!profile) { setCatalog(await api.scenarios()); const p = await api.me(); setProfile(p); } })}>Retry status</button>}</div>}
    {!!retries.length && <section><h2>Unconfirmed requests — private to this browser</h2><p>These requests may already have succeeded. Retry sends the original saved payload, even if you edited the form. Refreshing status never regenerates an uncertain result.</p>{retries.map(key => <div key={key}><p>{key.split(':')[2]} request · {key.split(':').slice(3).join(' / ')}</p><button disabled={busy} onClick={() => void run(() => retrySaved(key))}>Retry original request</button><button disabled={busy} onClick={() => { sessionStorage.removeItem(key); setNotice('Saved retry discarded. Check status before sending again; a previous request may still complete.'); }}>Discard saved retry</button></div>)}</section>}
    {notice && <p role="status">{notice}</p>}{busy && <p role="status">Request in progress. Polling continues; do not create a new request if the connection fails.</p>}
  </>;
  function createRoom() {
    if (!profile) return;
    void run(async () => {
      const key = `echorole:${profile.user_id}:create`;
      const body = pending(key, {request_id: crypto.randomUUID()});
      const room = await api.createRoom(body.request_id);
      selectRoom(room.id);
      sessionStorage.removeItem(key);
    });
  }
  function joinRoom(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get('code'));
    void run(async () => selectRoom((await api.join(code)).id));
  }
  function clearIdentity() {
    void run(async () => {
      if (roomId && !staleIdentity) await api.leave(roomId);
      await api.signout(); selectRoom(null); setProfile(null); setScore(0);
      setStaleIdentity(false); setPollError(''); setNotice(''); setCategory(''); setScenario('');
      for (const key of Object.keys(sessionStorage)) if (key.startsWith('echorole:')) sessionStorage.removeItem(key);
    });
  }
  if (boot || !roomId) return <Landing profile={profile} score={score} busy={busy} loading={boot} feedback={feedback} onProfile={profileForm} onCreate={createRoom} onJoin={joinRoom} onClearIdentity={clearIdentity} />;
  const s = data?.session, t = data?.turn;
  if (profile && !s) return <Lobby
    profile={profile} score={score} roomId={roomId} room={data?.room}
    members={data?.members} messages={data?.chat} catalog={catalog}
    category={category} scenarioId={scenario} chat={chat} busy={busy}
    pollError={pollError} feedback={feedback} onProfile={profileForm}
    onCategory={value => { setCategory(value); setScenario(''); }} onScenario={setScenario}
    onChat={setChat} onSendChat={() => void run(() => send('chat'))}
    onRefresh={() => void refresh()} onClearIdentity={clearIdentity}
    onLeave={() => void run(async () => { await api.leave(roomId); selectRoom(null); })}
    onStart={() => void run(async () => {
      const key = `echorole:${profile.user_id}:setup:${roomId}`;
      const body = pending<{scenario_id: string; expected_session_id?: number}>(key, {scenario_id: scenario, expected_session_id: undefined});
      await api.start(roomId, body.scenario_id, body.expected_session_id);
      sessionStorage.removeItem(key); clear();
    })}
  />;

  if (!profile || !data || !s || !t) return null;
  return <ActiveSession profile={profile} score={score} room={data.room} members={data.members} session={s} turn={t} role={data.private?.role_name} pollError={pollError}
    feedback={feedback}
    onRefresh={() => void refresh()}
    onLeave={() => void run(async () => { await api.leave(roomId); selectRoom(null); })}
    busy={busy}
    profileForm={<><details ><summary>Edit profile</summary><form onSubmit={profileForm} key={profile?.user_id ?? 'new'}><label>Display name<input name="name" required defaultValue={profile?.display_name} /></label><label>MBTI (optional)<input name="mbti" defaultValue={profile?.mbti} /></label><label>Communication / value priorities<textarea name="priorities" defaultValue={profile?.priorities} /></label><button disabled={busy}>{profile ? 'Save profile' : 'Create profile'}</button></form></details><details><summary>Local identity</summary><button disabled={busy} onClick={clearIdentity}>Clear local identity</button></details></>}
    setup={<>{data && <details ><summary>Scenario setup{s ? ' / replace session' : ''}</summary><label>Category<select value={category} onChange={e => { setCategory(e.target.value); setScenario(''); }}><option value="">All categories</option>{[...new Set(catalog.map(x => x.category))].map(c => <option key={c}>{c}</option>)}</select></label><label>Scenario<select value={scenario} onChange={e => setScenario(e.target.value)}><option value="">Choose a scenario</option>{catalog.filter(x => !category || x.category === category).map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label>{!catalog.length && <p>No scenarios available.</p>}{catalog.filter(x => x.id === scenario).map(x => <div key={x.id}><Text>{x.context}</Text><Text>{x.conflict}</Text><Text>{x.opening_situation}</Text></div>)}<button disabled={busy || !scenario || !!pollError} onClick={() => void run(async () => { const key = `echorole:${profile.user_id}:setup:${roomId}`; const body = pending(key, {scenario_id: scenario, expected_session_id: s?.id}); await api.start(roomId, body.scenario_id, body.expected_session_id); sessionStorage.removeItem(key); clear(); })}>{s ? 'Replace session with selected scenario' : 'Start session'}</button></details>}</>}
    brief={<><section aria-label="Private role brief"><span className="section-label">PRIVATE · {data.private?.role_name === 'role_a' ? 'ROLE A' : 'ROLE B'} · TURN {t?.current_turn}</span><h2>Private role brief — only you</h2><p className="section-caption">Only visible to you.</p><Text>{data.private?.brief ?? ''}</Text><h3>Pressure</h3><Text>{data.private?.pressure || 'No additional pressure.'}</Text><h3>Next decision</h3><Text>{data.private?.next_decision_point || 'Review the shared situation.'}</Text><details><summary>Private brief history</summary>{data.private?.brief_history.map((b, i) => <div key={i}><h4>Turn {b.turn_number}</h4><Text>{b.brief_text}</Text></div>)}</details></section></>}
    coach={<><section><span className="section-label">YOUR PRIVATE NOTEBOOK</span><h2>AI Coach — private</h2><p className="section-caption">Pause, reflect, and explore a possible way forward.</p>{!data.coach?.length && <p>No Coach messages yet.</p>}<div className="coach-history" role="region" aria-label="Private reflection history" tabIndex={0}>{data.coach?.map((m, i) => <div className={m.sender === 'user' ? 'reflection' : 'coach-reply'} key={i}><strong>{m.sender === 'user' ? 'Your reflection' : 'Coach'} · Turn {m.turn_index}</strong><Text>{m.content}</Text></div>)}</div>{data.requests?.filter(r => r.state !== 'completed').map(r => <div key={r.request_id}><p>Coach request (turn {r.turn_index}): {r.state}</p>{r.state === 'uncertain' && <Recovery key={r.attempt_id} busy={busy} recover={() => void run(() => api.recoverCoach(s.id, r.request_id, {attempt_id: r.attempt_id, acknowledge_uncertain: true}))} />}{r.state === 'ready' && <button disabled={busy} onClick={() => void run(() => api.completeCoach(s.id, r.request_id))}>Save generated reply</button>}</div>)}<form onSubmit={e => { e.preventDefault(); void run(() => send('coach')); }}><label>Message your Coach<textarea value={coach} onChange={e => setCoach(e.target.value)} required /></label><button disabled={busy || !coach.trim() || !!pollError || data.requests?.some(r => r.state !== 'completed')}>Send reflection</button></form></section></>}
    guidance={<section><span className="section-label">PRIVATE GUIDANCE</span><h2>Suggested direction</h2><Text>{data.suggestion?.text || 'No suggestion yet. Suggestions appear after joint progression.'}</Text></section>}
    chat={<>{data && <section><h2>Shared chat — visible to the room</h2>{!data.chat.length && <p>No shared messages yet.</p>}{data.chat.map(m => <div key={m.id}><strong>{m.username ?? 'Participant'}</strong><Text>{m.content}</Text></div>)}<form onSubmit={e => { e.preventDefault(); void run(() => send('chat')); }}><label>Shared message<textarea value={chat} onChange={e => setChat(e.target.value)} required /></label><button disabled={busy || !chat.trim() || !!pollError}>Send message</button></form></section>}</>}
    peer={<>{s && data?.feedback && <section><h2>Peer feedback</h2>{data.feedback.feedback ? <><p>Feedback submitted: {data.feedback.feedback.star_rating} stars — {data.feedback.feedback.score_points} points</p><h3>Your private comment</h3><Text>{data.feedback.feedback.comment || 'No comment.'}</Text></> : !data.feedback.available ? <p>{data.feedback.reason}</p> : <form key={s.id} onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); const key = `echorole:${profile.user_id}:feedback:${s.id}`; const body = pending<PeerFeedbackSend>(key, {peer_user_id: data.feedback!.peer_user_id!, star_rating: Number(f.get('rating')), comment: String(f.get('comment'))}); void run(async () => { await api.sendFeedback(s.id, body); sessionStorage.removeItem(key); }); }}><p>How well did your partner handle this conversation?</p><p>Your feedback for: {data.feedback.peer_name}</p><label>Peer rating<select name="rating" required defaultValue=""><option value="" disabled>Select rating</option>{data.feedback.rating_options.map(o => <option key={o.star_rating} value={o.star_rating}>{o.star_rating} stars — {o.score_points} points</option>)}</select></label><label>Private comment<textarea name="comment" /></label><button disabled={busy || !!pollError}>Submit feedback</button></form>}</section>}</>}
    action={<><section><span className="section-label">YOUR MOVE</span><h2>{t.submitted ? 'A moment to listen.' : 'What will you do?'}</h2><p className="section-caption">Choose one concrete action that moves the conversation forward.</p>{t.own_action && <><h3>Your submitted action</h3><Text>{t.own_action}</Text></>}{t.state === 'uncertain' && t.attempt_id && <Recovery key={t.attempt_id} busy={busy} recover={() => void run(() => api.recover(s.id, t.turn_index, {attempt_id: t.attempt_id!, acknowledge_uncertain: true}))} />}{t.state === 'uncertain' ? null : t.state === 'generating' ? <p className="submission-status">Generating the next scene. Your action is saved; updates appear automatically.</p> : t.submitted ? <p className="submission-status">Action submitted. Waiting for the other participant or generation. Updates appear automatically.</p> : <form onSubmit={e => { e.preventDefault(); void run(() => send('action')); }}><label>Your action for turn {t.current_turn}<textarea value={action} onChange={e => setAction(e.target.value)} required /></label><button disabled={busy || !action.trim() || !!pollError}>Submit action</button></form>}{t.submitted && t.other_submitted && t.state !== 'uncertain' && <button disabled={busy || !!pollError} onClick={() => void run(() => api.complete(s.id, t.turn_index))}>Check / complete turn safely</button>}</section></>}
    history={<><section><h2>Progression history — shared</h2>{!data.history?.length && <p>No completed turns yet.</p>}{data.history?.map(h => <details key={h.turn_index}><summary>Turn {h.turn_index}</summary><Text>{h.resulting_situation}</Text></details>)}</section></>}
  />;
}
