# EchoRole FastAPI boundary — Phase 2

Run from the repository root with Python 3.10+:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
backend/.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
```

`application.py` is shared by Streamlit and FastAPI. FastAPI never imports
`app.py`, AI, or RAG. Its lifespan calls the same initialization entry point as
Streamlit. Imports do not open SQLite. `database.DB_NAME` defaults to the absolute
repository `echorole.db`; set `ECHOROLE_DB_PATH` before process startup to select
an alternate file. Use the same absolute path for both entry points. Existing
schema and initialization SQL are preserved. Phase 2 wraps stateful helpers in
a shared SQLite transaction; see the migration plan for retry semantics.

All paths below have prefix `/api/v1`:

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/health` | Process liveness |
| GET | `/scenarios`, `/scenarios/categories`, `/scenarios/{scenario_id}` | Existing public scenario catalog |
| POST | `/profiles` | `{display_name, mbti?, priorities?}`; creates UUID profile and returns bearer token (201) |
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
No API credentials are stored in a new database table.

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
assignment in that exact session. No private brief/coach/suggestion routes are
published yet. Future data queries must use the dependency's user and role scope.

SQLite `BEGIN IMMEDIATE` now covers membership checks/insertion, session setup,
role allocation and event versions in each shared service operation. Exceptions
roll back the entire operation. Busy/locked API writes return 503 with Retry-After.
No database constraints or tables were added; raw SQL bypassing these helpers is
not protected by a new uniqueness constraint. Existing duplicate data is not
rewritten. No AI, chat, actions, turns or UI workflows were migrated.

This is local development authentication: key or cookie theft permits
impersonation; no password/account recovery or individual token revocation exists.
Losing/expiring the cookie cannot be repaired using a public UUID. Key rotation
invalidates all issued credentials. Use loopback HTTP only for development, and
HTTPS/Secure cookies and real authentication before external exposure.

Tests use disposable databases and compare sqlite_master against the original
initialization implementation. Install Streamlit and streamlit-autorefresh in the
legacy environment to run `python -m streamlit run app.py`; they are not backend
runtime dependencies.
