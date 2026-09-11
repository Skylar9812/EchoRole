import "server-only";

type HealthResponse = { status: "ok"; service: "echorole-api" };

/** Server-side HTTP boundary. No database, Python, or secret access in the browser. */
export async function getApiHealth(): Promise<HealthResponse | null> {
  try {
    const baseUrl = process.env.ECHOROLE_API_URL ?? "http://127.0.0.1:8000";
    const response = await fetch(new URL("/api/v1/health", baseUrl), {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    if (typeof data !== "object" || data === null ||
        !("status" in data) || data.status !== "ok" ||
        !("service" in data) || data.service !== "echorole-api") return null;
    return { status: data.status, service: data.service };
  } catch {
    return null;
  }
}

export const identityCookie = "echorole_identity";
export const identityMaxAge = 30 * 24 * 60 * 60;

/** Called only by server handlers; browser Authorization headers are never trusted. */
export async function participantApi(
  path: string,
  method: "GET" | "POST",
  token?: string,
  body?: string,
): Promise<Response> {
  const baseUrl = process.env.ECHOROLE_API_URL ?? "http://127.0.0.1:8000";
  return fetch(new URL(`/api/v1/${path}`, baseUrl), {
    method,
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(120000),
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body,
  });
}


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
