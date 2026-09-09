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
