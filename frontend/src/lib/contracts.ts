export type TurnStatus = {
  session_id: number; turn_index: number; current_turn: number;
  state: "action_required" | "submitted" | "waiting_for_other" | "generating" | "advanced" | "uncertain";
  submitted: boolean; other_submitted: boolean; own_action: string | null;
  attempt_id: string | null; current_situation: string;
};
export type SharedMessage = { id: number; user_id: string; username: string | null; content: string; created_at: string };
export type PrivateState = {
  session_id: number; turn_index: number; role_name: "role_a" | "role_b"; brief: string;
  brief_history: { turn_number: number; brief_text: string; created_at: string }[];
  pressure: string; next_decision_point: string;
};
export type CoachResult = {
  request_id: string; turn_index: number; attempt_id: string;
  state: "running" | "ready" | "completed" | "uncertain"; reply: string | null;
};
export type CoachMessage = { turn_index: number; sender: "user" | "ai"; content: string; created_at: string };
export type Suggestion = { turn_index: number; text: string };
export type ProgressionEntry = { turn_index: number; resulting_situation: string; created_at: string };
// Callers keep request_id stable on transport retries. Never automatically recover
// an uncertain provider outcome; recover requires attempt_id + explicit acknowledgement.
export type ChatSend = { request_id: string; content: string };
export type CoachSend = ChatSend & { turn_index: number };
export type ActionSend = { turn_index: number; action_text: string };
export type Recovery = { attempt_id: string; acknowledge_uncertain: true };

export type Profile = { user_id: string; display_name: string; mbti: string; priorities: string };
export type ProfileInput = Omit<Profile, 'user_id'>;
export type Room = { id: number; invite_code: string; event_version: number; created_at: string };
export type Member = { user_id: string; nickname: string | null; joined_at: string };
export type Scenario = { id: string; title: string; category: string; context: string; conflict: string; opening_situation: string };
export type Session = Omit<Scenario, 'id' | 'category'> & { id: number; room_id: number; current_turn: number; current_situation: string; created_at: string };
