import { NextRequest, NextResponse } from "next/server";
import { identityCookie, identityMaxAge, participantApi } from "@/lib/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };
const noStore = { "Cache-Control": "no-store" };

function json(data: unknown, status = 200) {
  return NextResponse.json(data, { status, headers: noStore });
}

async function handle(request: NextRequest, context: Context) {
  const path = (await context.params).path.join("/");
  const method = request.method;
  // Exact allowlist: this is not an arbitrary authenticated reverse proxy.
  const allowed = method === "GET"
    ? /^(scenarios|me|rooms\/[1-9]\d*(\/(members|session|messages))?|sessions\/[1-9]\d*\/(private|suggestion|progression|turn(\/status)?|coach\/(messages|requests(\/[A-Za-z0-9_-]+)?)))$/.test(path)
    : method === "POST"
      ? /^(profiles|me|rooms|rooms\/join|rooms\/[1-9]\d*\/(join|leave|sessions|messages)|sessions\/[1-9]\d*\/(turn\/(actions|complete|recover)|coach\/(messages|requests\/[A-Za-z0-9_-]+\/(recover|complete))))$/.test(path)
      : method === "DELETE" && path === "identity";
  if (!allowed) return json({ detail: "Not found" }, 404);
  if (method !== "GET") {
    const origin = process.env.ECHOROLE_WEB_ORIGIN ?? "http://127.0.0.1:3000";
    if (request.headers.get("origin") !== origin || request.headers.get("sec-fetch-site") === "cross-site") {
      return json({ detail: "Same-origin request required" }, 403);
    }
  }
  if (method === "DELETE") {
    const response = json({ status: "signed_out" });
    response.cookies.set(identityCookie, "", { httpOnly: true, sameSite: "strict", path: "/", maxAge: 0 });
    return response;
  }
  const token = request.cookies.get(identityCookie)?.value;
  if (!token && path !== "profiles" && path !== "scenarios") return json({ detail: "Identity required" }, 401);
  try {
    // Repeated profile requests recover the cookie's identity, never overwrite it.
    if (path === "profiles" && token) {
      const existing = await participantApi("me", "GET", token);
      return json(await existing.json(), existing.status);
    }
    const body = method === "POST" ? (await request.text() || undefined) : undefined;
    const turnIndex = request.nextUrl.searchParams.get("turn_index");
    if (turnIndex !== null && !/^[1-9]\d*$/.test(turnIndex)) return json({ detail: "Invalid turn index" }, 422);
    const upstreamPath = turnIndex ? `${path}?turn_index=${turnIndex}` : path;
    const upstream = await participantApi(upstreamPath, method as "GET" | "POST", token, body);
    const data = await upstream.json();
    if (path === "profiles" && upstream.ok) {
      const { access_token, token_type: _tokenType, ...profile } = data;
      if (typeof access_token !== "string") return json({ detail: "Invalid identity response" }, 502);
      const response = json(profile, upstream.status);
      response.cookies.set(identityCookie, access_token, {
        httpOnly: true,
        sameSite: "strict",
        secure: process.env.ECHOROLE_COOKIE_SECURE !== "false",
        path: "/",
        maxAge: identityMaxAge,
      });
      return response;
    }
    return json(data, upstream.status);
  } catch {
    return json({ detail: "EchoRole API unavailable" }, 502);
  }
}

export const GET = handle;
export const POST = handle;
export const DELETE = handle;
