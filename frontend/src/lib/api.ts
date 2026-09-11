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
    signal: AbortSignal.timeout(10000),
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body,
  });
}
