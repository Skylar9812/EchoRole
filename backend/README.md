# EchoRole FastAPI boundary — Phase 3

Run from the repository root with Python 3.10+:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
backend/.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
```

`application.py` is shared by Streamlit and FastAPI. FastAPI never imports
`app.py`. AI/RAG are loaded lazily by the shared interactive service. The FastAPI
lifespan calls the same initialization entry point as Streamlit. Imports do not open SQLite. `database.DB_NAME` defaults to the absolute
repository `echorole.db`; set `ECHOROLE_DB_PATH` before process startup to select
an alternate file. Use the same absolute path for both entry points. Phase 3 adds
only `operation_journal` to the existing schema, as explicitly approved. Existing tables and uniqueness indexes are unchanged; see the migration
plan for claim, recovery and retry semantics.

All paths below have prefix `/api/v1`:

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/health` | Process liveness |
| GET | `/scenarios`, `/scenarios/categories`, `/scenarios/{scenario_id}` | Existing public scenario catalog |
| POST | `/profiles/prepare` | Issues signed enrollment credential; no profile write |
| POST | `/profiles` | Enrollment bearer required; `{display_name, mbti?, priorities?}`; atomic create/replay, returns identity bearer (201) |
| GET | `/me` | Recover the authenticated profile without returning a token |
| POST | `/rooms` | No body; creates room and adds caller (201) |
| POST | `/rooms/{room_id}/join` | No body; joins caller, activating available role if a session exists |
| GET | `/rooms/{room_id}` | Public room metadata and event version; membership required |
| GET | `/rooms/{room_id}/members` | Ordered public member list; membership required |
| POST | `/rooms/{room_id}/sessions` | `{scenario_id, expected_session_id?}`; membership required; atomic create/retry (201) |
| GET | `/rooms/{room_id}/session` | Public current session, or JSON null in lobby; membership required |

Use `Authorization: Bearer <access_token>` for `/me` and every room endpoint.
`POST /profiles` creates a UUID and signed 30-day credential, never accepting a
caller-selected user ID. The API persists a random signing key beside the database
at `<database path>.identity-key`, atomically publishing it on first startup.
Alternatively configure `ECHOROLE_IDENTITY_SECRET` with at least 32 random bytes
represented as a string, consistently across workers. Keys are ignored by Git.
No API credentials are stored in the operation journal.

`GET /me` recovers the same profile after restart with the existing credential.
Browser callers should use the Next.js `/api/echorole/*` handlers, which keep the
credential in an HttpOnly cookie and omit it from browser JSON. See the frontend
README and migration plan. Existing Streamlit URL IDs are not credentials and
cannot be used to claim profiles through this API.

Responses use explicit allowlists; public session data excludes role briefs,
role perspectives, private coach content, and complete database records. Errors
use `detail`: 401 for missing/invalid identity, 403 for non-members, 404 for missing
rooms/scenarios, 409 for legacy capacity/role limits, and 422 for invalid contracts.

Session creation is idempotent for the current scenario. Another scenario without
the current `expected_session_id` returns 409. Supplying that current ID explicitly
requests a replacement, including restarting the same scenario; retrying that
replacement returns the current matching session without inserting again. Public
session reads remain current-state reads, not historical response replay.

Roles still follow membership order, role_a then role_b. Late arrivals receive
the first vacant role, and returning participants retain their assignment. Both
active-member and reserved-role limits remain. Joining with unchanged membership
and nickname does not bump the event version on retry. Streamlit retains its URL
restoration, UI feedback, sync callbacks and reruns.

`backend/authorization.py` provides room-member, session-participant and role-owner
dependencies. A session participant needs both current room membership and an
assignment in that exact session. Private brief/Coach/suggestion routes use the
dependency's authenticated user and role; request bodies cannot override them.

SQLite `BEGIN IMMEDIATE` now covers membership checks/insertion, session setup,
role allocation and event versions in each shared service operation. Exceptions
roll back the entire operation. Busy/locked API writes return 503 with Retry-After.
The new operation journal has a unique operation key and checked lifecycle states.
Legacy uniqueness indexes still protect actions, history, stories and suggestions.
Do not bypass the shared interactive service with legacy raw claim/reset helpers.

This is local development authentication: key or cookie theft permits
impersonation; no password/account recovery or individual token revocation exists.
Losing/expiring the cookie cannot be repaired using a public UUID. Key rotation
invalidates all issued credentials. Use loopback HTTP only for development, and
HTTPS/Secure cookies and real authentication before external exposure.

Tests use disposable databases, verify the old schema is unchanged apart from
the approved operation journal, and verify in-place legacy upgrades preserve data. Install Streamlit and streamlit-autorefresh in the
legacy environment to run `python -m streamlit run app.py`; they are not backend
runtime dependencies.


Phase 3 interactive endpoints (prefix `/api/v1`):

| Method | Path | Contract |
| --- | --- | --- |
| GET/POST | `/rooms/{room_id}/messages` | Ordered room chat; POST `{content, request_id}` |
| GET | `/sessions/{session_id}/private` | Own evolved brief/history, role pressure and decision point |
| GET | `/sessions/{session_id}/roles/{role_name}/private` | Same own-role projection; another role returns 403 |
| GET/POST | `/sessions/{session_id}/coach/messages` | Own visible messages; POST `{content, request_id, turn_index}` |
| GET | `/sessions/{session_id}/coach/requests` | Own durable request states, including interrupted requests |
| GET | `/sessions/{session_id}/coach/requests/{request_id}` | Own request state/result |
| POST | `/sessions/{session_id}/coach/requests/{request_id}/complete` | Persist an already saved reply, without another provider call |
| POST | `/sessions/{session_id}/coach/requests/{request_id}/recover` | `{attempt_id, acknowledge_uncertain: true}` |
| GET | `/sessions/{session_id}/suggestion` | Own current-turn suggestion, generated with the joint story |
| GET | `/sessions/{session_id}/turn`, `/sessions/{session_id}/turn/status` | Current situation, own action and submission flags |
| POST | `/sessions/{session_id}/turn/actions` | `{turn_index, action_text}`; may complete the joint turn |
| POST | `/sessions/{session_id}/turn/complete` | `{turn_index}`; claim once or persist a saved result |
| POST | `/sessions/{session_id}/turn/recover` | `{turn_index, attempt_id, acknowledge_uncertain: true}` |
| GET | `/sessions/{session_id}/progression` | Shared resulting situations in turn order |

GET Coach messages and turn/status accept optional positive `turn_index`.
All session endpoints require both room membership and an assignment in that exact
session. Shared projections never serialize private briefs, Coach content, role
perspectives, suggestions or another participant's pending action. Initial hidden
Coach prompts/action records/validation notices are filtered from visible chat.
All API responses disable caching.

Chat and Coach request IDs must be 1–128 letters/digits/underscore/hyphen. Keep the
same ID and payload on retry. Conflicting reuse returns 409. A different ID means
a new message; the API does not deduplicate identical text sent intentionally twice.
Accepted actions are immutable (matching Streamlit's disabled submit form). Exact
replays of completed actions return `advanced`; different stale submissions return
409. Replacing a session with pending actions is blocked.

A normal completed generation runs once; SQLite atomically commits turn history,
story state, both private suggestions, action records, consumption, event version,
turn advancement and journal completion. Generated results are durably saved before
this final transaction, allowing recovery from a later persistence failure.

A provider exception, network loss/server error observed through the existing
transport, or a claim older than 15 minutes is `uncertain`. Ordinary requests do not
invoke the provider again. Recovery requires the current attempt ID and explicit
acknowledgement; it creates a new fenced attempt using the frozen original inputs.
A late response from the old attempt cannot overwrite the new result. Uncertainty
cannot guarantee the external provider did no work: recovery may repeat that work,
but database completion/advancement remains exactly once. Recovery while an attempt
is still running and not expired returns 409. Existing local/missing-key fallback
and all prompts remain available. The journal holds sensitive captured context;
there is no raw-journal endpoint.

Suggestions use the existing joint-generation output. Turn 1 may have no suggestion;
there is no invented standalone suggestion prompt or independent suggestion call.
`ai_messages.py` remains an unmodified diagnostic script; importing it would open a
relative database. Services reuse the existing `database.py` AI-message helpers.

Run the offline active Streamlit check from the repository root:

```powershell
backend/.venv/Scripts/python -m backend.tests.streamlit_smoke
```

It uses the existing local AI provider and disposable SQLite data, exercising chat,
Coach, submission/waiting, joint advancement and evolved role/suggestion rendering.

## Phase 4 browser support additions

- `POST /me` accepts `ProfileCreate` and updates only the authenticated profile,
  synchronizing existing membership nicknames/event versions atomically.
- `POST /rooms` optionally accepts `{request_id}`. The shared Python service uses
  a participant-scoped SHA-256-derived 24-character invite code for atomic replay.
  No new table/index is added. Existing no-body clients retain six-character codes.
- `POST /rooms/join` accepts `{invite_code}`; resolves and joins atomically using
  existing capacity/role rules. Input is trimmed and case-normalized.
- `POST /rooms/{room_id}/leave` removes only the caller's membership, bumps the
  event version once, and is safe to repeat. Role reservations remain unchanged,
  matching Streamlit; leaving immediately removes access to private APIs.

These paths plus public scenario previews are explicitly allowed by Next.js.
The frontend adds no database, AI, or room/session business logic.


## Phase 4.5 parity additions

`POST /profiles/prepare` returns `{enrollment_token}` to the server-side transport.
It is a signed, random UUID credential with purpose `enroll`, domain-separated from
`v1` identity tokens and valid for 30 days under the existing persistent signing key.
It creates no database rows. `POST /profiles` now requires that credential as Bearer;
missing/invalid/expired/wrong-purpose credentials return 401. Atomic create-or-read
uses the credential UUID and the existing profile primary key; the first committed
payload wins and later retries return the current profile without overwriting it.
This works across workers/restarts, with no schema change. Clients must finish and
retain preparation before creation. Next.js stores it only in an HttpOnly cookie,
returns `{status: "ready"}`, requires mutation Origin and strips all credentials from
browser JSON. Enrollment credentials never authorize any other endpoint.

- `GET /me/score` → `{total_points}` for the authenticated participant only.
- `GET /sessions/{id}/peer-feedback` → eligibility/reason, current peer ID/name,
  Python-supplied rating options/points and the caller's own saved feedback or null.
- `POST /sessions/{id}/peer-feedback` → same projection; body
  `{peer_user_id, star_rating, comment?}`. Caller/room are derived from authentication
  and session. Both parties must be current members and assigned in this session;
  new feedback requires the current session and turn >= 3. Changed target or
  unavailable feedback returns 409; invalid ratings return 422.

Existing half-star UI values (0.5–5) go through the legacy database scoring helper:
ten points per star, summed across all sessions for the recipient. The existing
unique key enforces one rating per session/rater/recipient. The shared atomic service
returns the first saved feedback on duplicate submissions (even edited retries),
without duplicate points or event updates. Comments remain author-private, matching
Streamlit; no received-comment or arbitrary user's score endpoint is added.
Streamlit now uses the same feedback submission/eligibility and score service.


## Local real-model demo

Set `ECHOROLE_AI_PROVIDER=llm`, `ECHOROLE_LLM_API_KEY`,
`ECHOROLE_LLM_API_BASE`, and `ECHOROLE_LLM_MODEL` in the backend process environment.
The provider base must support OpenAI-compatible `/chat/completions`; omit that
suffix. Existing defaults are `https://api.deepseek.com` and `deepseek-v4-flash`.
`DEEPSEEK_API_KEY` remains a supported alias. Use a model available to your account.
FastAPI loads the project-root `.env` through python-dotenv before importing
application configuration, independently of the working directory. Existing OS
environment variables take precedence (including explicitly empty values).
Values are loaded literally without interpolation and are never logged by the loader.
Root `.env.example` lists variables; copy it to `.env` for local credentials.
Local `.env*` secrets are ignored. Never put keys in NEXT_PUBLIC variables.
Restart FastAPI after setting configuration. Set `ECHOROLE_DB_PATH` to a fresh
local demo database and use fresh browser contexts; do not rewrite old messages.

Missing keys / malformed base URLs produce a clear 503 before new generation
claims. Provider failures and invalid output cannot save local templates as
success: existing uncertain-operation recovery requires acknowledgement.
Fix credentials before attempting recovery. Offline tests retain explicit local mode.
Coach uses profile, role, scenario, turn, current situation and reflection context.
RAG retrieval is included on the first Coach response (embedding retrieval with
lexical fallback); later replies use recent conversation. Joint generation uses
both actions, role/session context, turn history and shared chat, without RAG.
Private suggestions come from the same joint model result, not a separate call.
Initial briefs are scenario data; evolved briefs retain deterministic assembly.
A real key is required for external verification; offline tests are not proof of
real-model generation.


## Room language and editable feedback

Initialization additively migrates `rooms.language` to a non-null, constrained
`en` / `zh-CN` / `zh-TW` value. Existing rooms default to English. Room creation
accepts `language`; no room-language update route exists. Replaying a successful
creation request preserves the original room and its language. Members receive
that language in room responses. `GET /scenarios?language=...` localizes public
scenario fields; shared session creation localizes static private briefs using
the persisted room language and the original scenario ID. Translations live in
`locales/scenarios.*.json`; the original English library remains unchanged.

AI operation inputs capture the trusted room language. Prompt builders apply it
to Coach, action guidance and joint generation, including private suggestions and
updated briefs. User input and RAG content are not translated. Provider transport,
selection, retries, recovery and the operation journal are unchanged. The explicit
local deterministic provider remains an English offline/demo implementation;
room-controlled generated language applies to real LLM responses.

`POST /sessions/{id}/peer-feedback` accepts an optional `request_id`. With an ID,
whole-star ratings can be edited; an atomic deduplication record prevents retry
replays from overwriting later ratings. Same-ID/different-payload requests conflict.
The latest rating contributes 10–50 points rather than accumulating on each edit.
Private comments remain visible only to their author. The additive
`peer_feedback_requests` table is separate from the AI operation journal. Legacy
clients omitting request IDs retain their existing first-write-wins semantics.
