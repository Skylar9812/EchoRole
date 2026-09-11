# EchoRole Next.js boundary

The landing page remains unchanged. Phase 2 adds server handlers and credential
transport only; no visual identity, lobby or session UI is implemented.

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
Set `ECHOROLE_NODE` to the Node executable if it is not on PATH. No UI or provider
calls are involved; servers are stopped after verification.
