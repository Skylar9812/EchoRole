'use client';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, pending } from '@/lib/client';
import type { Profile, ProfileInput, Room, Member, Scenario, Session, SharedMessage, PrivateState, CoachMessage, CoachResult, Suggestion, TurnStatus, ProgressionEntry, ChatSend, CoachSend, ActionSend } from '@/lib/contracts';

type Snapshot = { room: Room; members: Member[]; session: Session | null; chat: SharedMessage[]; private?: PrivateState; coach?: CoachMessage[]; requests?: CoachResult[]; suggestion?: Suggestion; turn?: TurnStatus; history?: ProgressionEntry[] };
function Text({children}: {children: string}) { return <p className="text">{children}</p>; }
function Recovery({busy, recover}: {busy: boolean; recover: () => void}) {
  const [ack, setAck] = useState(false);
  return <div role="alert"><p>Generation outcome is uncertain. An earlier AI request may have run. Recovery can repeat external AI work; it will not advance the database turn twice.</p><label><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} /> I acknowledge that recovery may repeat the AI request.</label><button disabled={!ack || busy} onClick={recover}>Recover generation</button></div>;
}
export default function EchoRole() {
  const [profile, setProfile] = useState<Profile | null>(null), [boot, setBoot] = useState(true);
  const [roomId, setRoomId] = useState<number | null>(null), [data, setData] = useState<Snapshot | null>(null);
  const [catalog, setCatalog] = useState<Scenario[]>([]), [category, setCategory] = useState(''), [scenario, setScenario] = useState('');
  const [error, setError] = useState(''), [pollError, setPollError] = useState(''), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [chat, setChat] = useState(''), [coach, setCoach] = useState(''), [action, setAction] = useState('');
  const epoch = useRef(0), locked = useRef(false), polling = useRef(false);
  const clear = useCallback(() => { epoch.current++; setData(null); setChat(''); setCoach(''); setAction(''); }, []);
  const selectRoom = useCallback((id: number | null) => { clear(); setRoomId(id); if (id) sessionStorage.setItem('echorole-room', String(id)); else sessionStorage.removeItem('echorole-room'); }, [clear]);
  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) { clear(); setProfile(null); setRoomId(null); setError('Identity missing or expired. Clear the local identity to create a new profile.'); }
    else setError(`${e instanceof ApiError && e.status === 409 ? 'State changed or stale turn. Refresh status before retrying. ' : ''}${e instanceof Error ? e.message : 'Request failed'}`);
  }, [clear]);
  const refresh = useCallback(async () => {
    if (!roomId || !profile || polling.current) return;
    polling.current = true; const version = epoch.current;
    try {
      const [room, members, session, messages] = await Promise.all([api.room(roomId), api.members(roomId), api.session(roomId), api.chat(roomId)]);
      const next: Snapshot = {room, members, session, chat: messages};
      if (session) {
        const [privateState, coachMessages, requests, suggestion, turn, history] = await Promise.all([api.private(session.id), api.coach(session.id), api.requests(session.id), api.suggestion(session.id), api.turn(session.id), api.history(session.id)]);
        // A turn can advance between reads. Publish only a consistent projection.
        if (turn.current_turn !== session.current_turn || privateState.turn_index !== turn.current_turn || suggestion.turn_index !== turn.current_turn) return;
        Object.assign(next, {private: privateState, coach: coachMessages, requests, suggestion, turn, history});
      }
      if (epoch.current === version) { setData(previous => { if (previous?.session?.id !== session?.id || previous?.turn?.current_turn !== next.turn?.current_turn) { setAction(''); setNotice(previous?.session ? 'Session updated. Review your current brief before acting.' : ''); } return next; }); setPollError(''); }
    } catch (e) { if (version === epoch.current) { if (e instanceof ApiError && (e.status === 401 || e.status === 403)) { clear(); fail(e); } setPollError(e instanceof Error ? e.message : 'Refresh failed'); } }
    finally { polling.current = false; }
  }, [roomId, profile, clear, fail]);
  useEffect(() => { let live = true; Promise.all([api.me().catch(e => { if (e instanceof ApiError && e.status === 401) return null; throw e; }), api.scenarios()]).then(([p, c]) => { if (!live) return; setProfile(p); setCatalog(c); if (p) { const id = Number(sessionStorage.getItem('echorole-room')); if (id > 0) setRoomId(id); } }).catch(fail).finally(() => { if (live) setBoot(false); }); return () => { live = false; }; }, [fail]);
  useEffect(() => { let live = true; let timer: ReturnType<typeof setTimeout>; const tick = async () => { if (!document.hidden) await refresh(); if (live) timer = setTimeout(tick, 2500); }; void tick(); const visible = () => { if (!document.hidden) void refresh(); }; document.addEventListener('visibilitychange', visible); window.addEventListener('online', visible); return () => { live = false; clearTimeout(timer); document.removeEventListener('visibilitychange', visible); window.removeEventListener('online', visible); }; }, [refresh]);
  async function run(work: () => Promise<unknown>) { if (locked.current) return; locked.current = true; setBusy(true); setError(''); try { await work(); await refresh(); } catch (e) { fail(e); } finally { locked.current = false; setBusy(false); } }
  function profileForm(e: FormEvent<HTMLFormElement>) { e.preventDefault(); const f = new FormData(e.currentTarget); const input: ProfileInput = {display_name: String(f.get('name')).trim(), mbti: String(f.get('mbti')), priorities: String(f.get('priorities'))}; void run(async () => setProfile(await api.profile(input, !!profile))); }
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
  const retries = profile ? Object.keys(sessionStorage).filter(k => k.startsWith(`echorole:${profile.user_id}:`) && /:(chat|coach|action|setup):/.test(k)) : [];
  async function retrySaved(key: string) {
    const raw = sessionStorage.getItem(key); if (!raw) return;
    const parts = key.split(':'); const kind = parts[2], id = Number(parts[3]);
    if (kind === 'setup') { const body = JSON.parse(raw) as {scenario_id: string; expected_session_id?: number}; await api.start(id, body.scenario_id, body.expected_session_id); }
    if (kind === 'chat') await api.sendChat(id, JSON.parse(raw) as ChatSend);
    if (kind === 'coach') await api.sendCoach(id, JSON.parse(raw) as CoachSend);
    if (kind === 'action') await api.action(id, JSON.parse(raw) as ActionSend);
    sessionStorage.removeItem(key);
  }
  if (boot) return <main><h1>EchoRole</h1><p role="status">Loading profile and scenarios…</p></main>;
  const s = data?.session, t = data?.turn;
  return <main><h1>EchoRole</h1><p>Profile → Room → Scenario → Session</p>
    {error && <div role="alert"><p>{error}</p><button disabled={busy} onClick={() => void run(async () => { await refresh(); if (!profile) { setCatalog(await api.scenarios()); const p = await api.me(); setProfile(p); } })}>Retry status</button></div>}
    {!!retries.length && <section><h2>Unconfirmed requests — private to this browser</h2><p>These requests may already have succeeded. Retry sends the original saved payload, even if you edited the form. Refreshing status never regenerates an uncertain result.</p>{retries.map(key => <div key={key}><p>{key.split(':')[2]} request · {key.split(':').slice(3).join(' / ')}</p><button disabled={busy} onClick={() => void run(() => retrySaved(key))}>Retry original request</button><button disabled={busy} onClick={() => { sessionStorage.removeItem(key); setNotice('Saved retry discarded. Check status before sending again; a previous request may still complete.'); }}>Discard saved retry</button></div>)}</section>}
    {notice && <p role="status">{notice}</p>}{busy && <p role="status">Request in progress. Polling continues; do not create a new request if the connection fails.</p>}
    <details open={!profile}><summary>Profile{profile ? `: ${profile.display_name}` : ''}</summary><form onSubmit={profileForm} key={profile?.user_id ?? 'new'}><label>Display name<input name="name" required defaultValue={profile?.display_name} /></label><label>MBTI (optional)<input name="mbti" defaultValue={profile?.mbti} /></label><label>Communication / value priorities<textarea name="priorities" defaultValue={profile?.priorities} /></label><button disabled={busy}>{profile ? 'Save profile' : 'Create profile'}</button></form></details>
    <button disabled={busy} onClick={() => void run(async () => { if (roomId) await api.leave(roomId); await api.signout(); selectRoom(null); setProfile(null); for (const k of Object.keys(sessionStorage)) if (k.startsWith('echorole:')) sessionStorage.removeItem(k); })}>Clear local identity</button>
    {profile && !roomId && <section><h2>Create or join a room</h2><button disabled={busy} onClick={() => void run(async () => { const key = `echorole:${profile.user_id}:create`; const body = pending(key, {request_id: crypto.randomUUID()}); const r = await api.createRoom(body.request_id); selectRoom(r.id); sessionStorage.removeItem(key); })}>Create room</button><form onSubmit={e => { e.preventDefault(); const code = String(new FormData(e.currentTarget).get('code')); void run(async () => selectRoom((await api.join(code)).id)); }}><label>Invite code<input name="code" required /></label><button disabled={busy}>Join room</button></form></section>}
    {profile && roomId && <><section><h2>{s ? 'Active session' : 'Lobby'} — Room {roomId}</h2><p>Invite code: <strong>{data?.room.invite_code ?? 'Loading…'}</strong></p>{pollError && <p role="alert">Updates unavailable: {pollError}. Displayed data may be stale.</p>}<button onClick={() => void refresh()}>Refresh status</button><button disabled={busy} onClick={() => void run(async () => { await api.leave(roomId); selectRoom(null); })}>Leave room</button><h3>Participants</h3>{data ? <ul>{data.members.map(m => <li key={m.user_id}>{m.nickname ?? 'Participant'}{m.user_id === profile.user_id ? ' (you)' : ''}</li>)}</ul> : <p>Loading room…</p>}{data?.members.length === 1 && <p>Waiting for another participant. Share the invite code.</p>}</section>
    {data && <details open={!s}><summary>Scenario setup{s ? ' / replace session' : ''}</summary><label>Category<select value={category} onChange={e => { setCategory(e.target.value); setScenario(''); }}><option value="">All categories</option>{[...new Set(catalog.map(x => x.category))].map(c => <option key={c}>{c}</option>)}</select></label><label>Scenario<select value={scenario} onChange={e => setScenario(e.target.value)}><option value="">Choose a scenario</option>{catalog.filter(x => !category || x.category === category).map(x => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label>{!catalog.length && <p>No scenarios available.</p>}{catalog.filter(x => x.id === scenario).map(x => <div key={x.id}><Text>{x.context}</Text><Text>{x.conflict}</Text><Text>{x.opening_situation}</Text></div>)}<button disabled={busy || !scenario || !!pollError} onClick={() => void run(async () => { const key = `echorole:${profile.user_id}:setup:${roomId}`; const body = pending(key, {scenario_id: scenario, expected_session_id: s?.id}); await api.start(roomId, body.scenario_id, body.expected_session_id); sessionStorage.removeItem(key); clear(); })}>{s ? 'Replace session with selected scenario' : 'Start session'}</button></details>}
    {s && t && <><section><h2>{s.title} — Turn {t.current_turn}</h2><details><summary>Scenario context</summary><Text>{s.context}</Text><Text>{s.conflict}</Text></details><h3>Shared situation</h3><Text>{t.current_situation}</Text><p role="status">Turn status: {t.state}. You: {t.submitted ? 'submitted' : 'action needed'}. Other participant: {t.other_submitted ? 'submitted' : 'waiting'}.</p></section>
    <section aria-label="Private role brief"><h2>Private role brief — only you</h2><p>Your role: {data.private?.role_name}</p><Text>{data.private?.brief ?? ''}</Text><h3>Pressure</h3><Text>{data.private?.pressure || 'No additional pressure.'}</Text><h3>Next decision</h3><Text>{data.private?.next_decision_point || 'Review the shared situation.'}</Text><details><summary>Private brief history</summary>{data.private?.brief_history.map((b, i) => <div key={i}><h4>Turn {b.turn_number}</h4><Text>{b.brief_text}</Text></div>)}</details></section>
    <section><h2>AI Coach — private</h2>{!data.coach?.length && <p>No Coach messages yet.</p>}{data.coach?.map((m, i) => <div key={i}><strong>{m.sender === 'user' ? 'You' : 'Coach'} · Turn {m.turn_index}</strong><Text>{m.content}</Text></div>)}{data.requests?.filter(r => r.state !== 'completed').map(r => <div key={r.request_id}><p>Coach request (turn {r.turn_index}): {r.state}</p>{r.state === 'uncertain' && <Recovery key={r.attempt_id} busy={busy} recover={() => void run(() => api.recoverCoach(s.id, r.request_id, {attempt_id: r.attempt_id, acknowledge_uncertain: true}))} />}{r.state === 'ready' && <button disabled={busy} onClick={() => void run(() => api.completeCoach(s.id, r.request_id))}>Save generated reply</button>}</div>)}<form onSubmit={e => { e.preventDefault(); void run(() => send('coach')); }}><label>Message your Coach<textarea value={coach} onChange={e => setCoach(e.target.value)} required /></label><button disabled={busy || !coach.trim() || !!pollError || data.requests?.some(r => r.state !== 'completed')}>Send / retry Coach message</button></form><h3>Suggested direction</h3><Text>{data.suggestion?.text || 'No suggestion yet. Suggestions appear after joint progression.'}</Text></section>
    </>}
    {data && <section><h2>Shared chat — visible to the room</h2>{!data.chat.length && <p>No shared messages yet.</p>}{data.chat.map(m => <div key={m.id}><strong>{m.username ?? 'Participant'}</strong><Text>{m.content}</Text></div>)}<form onSubmit={e => { e.preventDefault(); void run(() => send('chat')); }}><label>Shared message<textarea value={chat} onChange={e => setChat(e.target.value)} required /></label><button disabled={busy || !chat.trim() || !!pollError}>Send / retry shared message</button></form></section>}
    {s && t && <><section><h2>Submit action</h2>{t.own_action && <><h3>Your submitted action</h3><Text>{t.own_action}</Text></>}{t.state === 'uncertain' && t.attempt_id && <Recovery key={t.attempt_id} busy={busy} recover={() => void run(() => api.recover(s.id, t.turn_index, {attempt_id: t.attempt_id!, acknowledge_uncertain: true}))} />}{t.submitted ? <p>Action submitted. Waiting for the other participant or generation. Updates appear automatically.</p> : <form onSubmit={e => { e.preventDefault(); void run(() => send('action')); }}><label>Your action for turn {t.current_turn}<textarea value={action} onChange={e => setAction(e.target.value)} required /></label><button disabled={busy || !action.trim() || !!pollError}>Submit / retry action</button></form>}{t.submitted && t.other_submitted && t.state !== 'uncertain' && <button disabled={busy || !!pollError} onClick={() => void run(() => api.complete(s.id, t.turn_index))}>Check / complete turn safely</button>}</section><section><h2>Progression history — shared</h2>{!data.history?.length && <p>No completed turns yet.</p>}{data.history?.map(h => <div key={h.turn_index}><h3>Turn {h.turn_index}</h3><Text>{h.resulting_situation}</Text></div>)}</section></>}
    </>}
  </main>;
}
