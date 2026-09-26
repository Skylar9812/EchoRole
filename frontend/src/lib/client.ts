import type { Language, Profile, ProfileInput, Room, Member, Scenario, Session, SharedMessage, PrivateState, CoachMessage, CoachResult, Suggestion, TurnStatus, ProgressionEntry, ChatSend, CoachSend, ActionSend, Recovery, PeerFeedbackState, PeerFeedbackSend, PeerScore } from './contracts';
export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) { super(message); }
}
async function request<T>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST'): Promise<T> {
  let response: Response;
  // Some embedded or older desktop browsers do not implement AbortSignal.timeout.
  // Do not fail every API call before it is sent merely because that optional
  // convenience API is unavailable.
  const timeout = typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
    ? AbortSignal.timeout(125000)
    : undefined;
  try { response = await fetch(`/api/echorole/${path}`, { method, credentials: 'same-origin', cache: 'no-store', headers: body === undefined ? {} : {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body), ...(timeout ? {signal: timeout} : {}) }); }
  catch { throw new ApiError(0, 'Connection interrupted. The request may still finish. Retry the same request or refresh status.'); }
  const data = await response.json();
  if (!response.ok) throw new ApiError(response.status, typeof data.detail === 'string' ? data.detail : 'Invalid request. Check the fields and retry.', data.code);
  return data as T;
}
export const api = {
  me: () => request<Profile>('me'), profile: async (p: ProfileInput, edit = false) => {
    if (edit) return request<Profile>('me', p);
    const enroll = async () => { await request<{status: string}>('profiles/prepare', {}); return request<Profile>('profiles', p); };
    // Serialize enrollment across tabs so a concurrent prepare cannot replace its cookie.
    return navigator.locks.request('echorole-enrollment', enroll);
  },
  score: () => request<PeerScore>('me/score'),
  feedback: (id: number) => request<PeerFeedbackState>(`sessions/${id}/peer-feedback`),
  sendFeedback: (id: number, body: PeerFeedbackSend) => request<PeerFeedbackState>(`sessions/${id}/peer-feedback`, body),
  signout: () => request('identity', undefined, 'DELETE'), scenarios: (language: Language = 'en') => request<Scenario[]>(`scenarios?language=${language}`),
  createRoom: (request_id: string, language: Language = 'en') => request<Room>('rooms', {request_id, language}), join: (invite_code: string) => request<Room>('rooms/join', {invite_code}),
  room: (id: number) => request<Room>(`rooms/${id}`), members: (id: number) => request<Member[]>(`rooms/${id}/members`),
  leave: (id: number) => request(`rooms/${id}/leave`, {}), session: (id: number) => request<Session | null>(`rooms/${id}/session`),
  start: (id: number, scenario_id: string, expected_session_id?: number) => request<Session>(`rooms/${id}/sessions`, {scenario_id, expected_session_id}),
  chat: (id: number) => request<SharedMessage[]>(`rooms/${id}/messages`), sendChat: (id: number, body: ChatSend) => request<SharedMessage>(`rooms/${id}/messages`, body),
  private: (id: number) => request<PrivateState>(`sessions/${id}/private`), coach: (id: number) => request<CoachMessage[]>(`sessions/${id}/coach/messages`),
  requests: (id: number) => request<CoachResult[]>(`sessions/${id}/coach/requests`), sendCoach: (id: number, body: CoachSend) => request<CoachResult>(`sessions/${id}/coach/messages`, body),
  completeCoach: (id: number, rid: string) => request<CoachResult>(`sessions/${id}/coach/requests/${rid}/complete`, {}),
  recoverCoach: (id: number, rid: string, body: Recovery) => request<CoachResult>(`sessions/${id}/coach/requests/${rid}/recover`, body),
  suggestion: (id: number) => request<Suggestion>(`sessions/${id}/suggestion`), turn: (id: number) => request<TurnStatus>(`sessions/${id}/turn`),
  action: (id: number, body: ActionSend) => request<TurnStatus>(`sessions/${id}/turn/actions`, body),
  complete: (id: number, turn_index: number) => request<TurnStatus>(`sessions/${id}/turn/complete`, {turn_index}),
  recover: (id: number, turn_index: number, body: Recovery) => request<TurnStatus>(`sessions/${id}/turn/recover`, {turn_index, ...body}),
  history: (id: number) => request<ProgressionEntry[]>(`sessions/${id}/progression`),
};
// Only pending outbound payloads are stored, tab-scoped and participant-scoped.
// Never store tokens, fetched private briefs, or Coach replies here.
export function pending<T>(key: string, body: T): T {
  const saved = sessionStorage.getItem(key);
  if (saved) return JSON.parse(saved) as T;
  sessionStorage.setItem(key, JSON.stringify(body));
  return body;
}
