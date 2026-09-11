# EchoRole Next.js boundary

The landing page remains unchanged. Phase 3 extends the existing server handlers and typed API contracts; no visual identity, lobby or session UI is implemented.

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Start FastAPI separately using `backend/README.md`. The default local browser
origin is `http://127.0.0.1:3000`. Use that exact origin, or update
`ECHOROLE_WEB_ORIGIN`. Set `ECHOROLE_API_URL` to the server-only FastAPI address;
never prefix it with `NEXT_PUBLIC_`.

Browser contract (all requests are same-origin):

- `POST /api/echorole/profiles` with `{display_name, mbti?, priorities?}` creates
  a profile through FastAPI and stores its signed token in an HttpOnly,
  SameSite=Strict, host-only cookie named `echorole_identity`, path `/`, age 30 days.
  The JSON response contains only the profile. If a cookie already exists, this
  request recovers that identity rather than replacing it.
- `GET /api/echorole/me` recovers the profile on refresh or after either server
  restarts. The browser sends the cookie automatically; no localStorage or
  JavaScript-readable token is used. An expired/invalid credential returns 401.
- Existing room routes are forwarded under `/api/echorole/rooms...`: create,
  join, room state, members, create session and current public session. Their
  bodies/statuses match the backend. The server reads only its cookie and sets
  `Authorization: Bearer ...` for FastAPI; it does not forward client-supplied
  Authorization or arbitrary URLs. This is an explicit route allowlist.
- `DELETE /api/echorole/identity` clears the local cookie. It does not revoke a
  previously copied token. After cookie loss, expiration or sign-out, creating a
  new profile gives a new UUID; there is no unverified account-claim mechanism.

Every mutation requires an Origin header exactly matching `ECHOROLE_WEB_ORIGIN`;
cross-site Fetch Metadata is rejected too. This supplements SameSite cookie
protection against CSRF. Reads and writes disable caching. Missing credentials
return 401, authorization failures 403, and unavailable FastAPI 502.

Secure cookies are the default. `.env.example` explicitly sets
`ECHOROLE_COOKIE_SECURE=false` **only for loopback HTTP development**. Use HTTPS
and remove that override outside local development. Keep the FastAPI process on
loopback; no browser-to-FastAPI CORS access is required. Cookie/key theft, XSS
acting through the browser, and local filesystem access remain security risks.
This provides a replaceable local identity boundary, not real account login.

```powershell
npm run build
npm run typecheck
npm start
```

After building, from the repository root:

```powershell
backend/.venv/Scripts/python frontend/tests/transport_smoke.py
```

The smoke test starts both servers against temporary SQLite data and checks cookie
flags, token omission, refresh/restart recovery, CSRF, authorization and sign-out.
Set `ECHOROLE_NODE` to the Node executable if it is not on PATH. No visual UI is exercised; the existing local provider is used without external
AI calls; servers are stopped after verification.


Phase 3 forwards shared room messages and participant session routes for private
briefs, Coach messages/request status/recovery, suggestions, turns/actions/completion/
recovery and progression. See the backend README for JSON contracts. The browser
still sends only its HttpOnly identity cookie; no caller-supplied user or role is
forwarded as authority. The optional `turn_index` query is validated before forwarding.
The explicit role-name private URL is intentionally not in the browser allowlist;
browser clients use `/sessions/{id}/private` for their own role.

Typed request/response contracts are exported by `src/lib/api.ts`. Keep chat/Coach
`request_id` stable across a timeout. The server timeout is 120 seconds; a timeout
is not proof that FastAPI stopped. Query the same request/turn status or resubmit
the same logical request. Never automatically call a recovery URL. An `uncertain`
state requires the user to acknowledge that an external AI call may be repeated,
then submit the displayed `attempt_id`. `ready` Coach results can be persisted via
its `/complete` URL without another provider call. No visual recovery UI has been
built for Next.js yet; Streamlit includes the explicit recovery controls.

The live transport smoke test also checks shared chat retries, role/Coach isolation,
action waiting, exactly-once progression, and private suggestion retrieval.
