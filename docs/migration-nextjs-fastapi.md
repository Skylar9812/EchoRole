# Next.js + FastAPI migration

Phase 2 hardens the shared stateful foundation on `migration/nextjs-fastapi`.
Phase 1 is preserved at `824a4f3`. No merge, push, deployment or visual redesign.

```text
Next.js same-origin server handlers -> FastAPI -> application.py
                                                    |
Streamlit app.py ------------------------------------+
                                                    |
                                   database.py / scenario_library.py
```

Identity and recovery:

- Profiles retain UUID, display name, MBTI and priorities. The API creates UUIDs;
  arbitrary client IDs and legacy Streamlit URL IDs are never accepted as proof.
- A fixed-format v1 token binds UUID, expiry and random nonce with HMAC-SHA256.
  It is valid for 30 days, and verification also checks the profile still exists.
- FastAPI startup loads `<absolute database path>.identity-key`, atomically
  publishing a random 32-byte key if missing. All workers using the same database
  share it. `ECHOROLE_IDENTITY_SECRET` may instead supply a stable random secret
  of at least 32 bytes. Keys and publication temporaries are ignored by Git.
- The existing cookie plus persistent key recover the same identity after browser
  refresh and API/Next.js restart via `GET /api/v1/me`. There is no trusted recovery
  after cookie loss/expiry; this phase does not add passwords or account claiming.
  Phase 1's in-memory tokens do not migrate. Key rotation invalidates all tokens.

Browser transport:

- Browser requests go to the explicit Next.js `/api/echorole/*` allowlist.
- Profile creation stores the returned credential in a host-only HttpOnly,
  SameSite=Strict cookie, path `/`, max-age 30 days. Tokens are removed from browser
  JSON, never put in localStorage, and forwarded as bearer credentials only by
  server code. Profile retries with an existing cookie recover that profile.
- Mutations require the exact configured Origin and reject cross-site Fetch
  Metadata. No-store responses/fetches prevent personalized caching. Secure cookies
  are default; loopback HTTP setup explicitly opts out in `.env.local`.
- Clearing the cookie signs out locally but does not revoke stolen copies.
  Filesystem/key theft or cookie theft enables impersonation. Loopback-only use
  and existing Streamlit's trusted local URL semantics remain development limits.
  See both application READMEs for configuration and endpoint contracts.

Authorization:

- `current_user`: valid signed credential and existing profile.
- `room_member`: authenticated caller currently belongs to that room.
- `session_member`: current room membership plus role assignment in the exact
  requested session. Knowing IDs or joining a different room is insufficient.
- `role_owner`: the requested role matches that session participant's assignment.
- Future own-brief/coach/suggestion routes must use these dependencies and scope
  their queries to the returned user and role. No private endpoints or AI features
  are published in this phase. Tests exercise real private briefs through test-only
  routes and prove another participant cannot select the caller's role.

Atomicity and retries:

- A database-owned `BEGIN IMMEDIATE` unit of work serializes checks and writes
  across threads and processes. Legacy helpers borrow its connection; only the
  outer operation commits/closes. An exception rolls back all membership/session/
  role/event-version writes. Initialization SQL and SQLite schema are unchanged.
- Repeated joins retain one member row and do not bump event versions when neither
  membership nor nickname changed. Active-member and reserved-role limits remain.
- Session creation atomically creates the scenario, ordered roles and event version.
  Retrying the current scenario returns its session without duplicate rows.
  A competing different scenario returns 409.
- To intentionally replace/restart a session, pass its current `expected_session_id`.
  A matching retry returns the resulting current session. A stale conflicting request
  returns 409. This is state-based idempotency, not an arbitrary request-key ledger or
  historical response replay. Public state may reflect later progression.
- Role allocation reuses a caller's role, chooses the first free role, and prevents
  both duplicate user assignments and conflicting ownership. Direct membership and
  role helper writes are serialized too. Existing duplicate rows are not repaired;
  unrelated raw SQL bypassing helpers is not covered by new uniqueness constraints.
- API SQLite lock timeouts return 503 with Retry-After. Room/profile creation is not
  generalized into a request-idempotency system in this phase.

Verification (2026-09-11):

- All 23 backend tests passed, including all Phase 1 regressions, identity recovery
  in a fresh process, credential rejection, private authorization, repeated writes,
  competing threads/processes, key publication, lock-timeout responses and injected-failure rollback.
- Next.js build and TypeScript checks passed. Live Next.js/FastAPI HTTP transport
  tests passed for HttpOnly cookie flags, no token in JSON, refresh/API-restart
  recovery, CSRF, membership checks, allowlisting and local sign-out.
- FastAPI and Streamlit returned HTTP 200. Streamlit AppTest rendered welcome,
  executed Create Room through the transaction layer, and rendered the lobby.
- All tests used disposable database/key files. sqlite_master equals baseline
  `460c149`; existing `echorole.db` SHA-256 is unchanged:
  `6C5FEB3A88FBE6A111D7D46B65C2162F506631816FAB09350FC9B85BC6414AD7`.
- No AI/turn interactions or frontend visual changes were made or verified.

Before shared chat/actions/turn migration, define the operation-specific retry keys,
atomic turn claims/completion and caller-scoped private data queries. Do not hold a
SQLite write lock while calling AI providers. Broader exposure also requires real
authentication, revocation/recovery, HTTPS, and a reviewed room-admission policy.
These are future-phase requirements; no chat/actions/progression/AI/WebSocket work
is included here. Local skill directories remain unstaged and uncommitted.
