# Next.js + FastAPI migration

Phase 1 adds the first shared stateful application layer on
`migration/nextjs-fastapi`. The original scaffold remains; Next.js is untouched.

```text
Streamlit app.py -> application.py <- FastAPI routes
                        |
              database.py / scenario_library.py
```

The shared module owns profile identity creation, database initialization entry,
room creation/join, room/member lookup, scenario session setup, role allocation
and public session projection. Database initialization SQL and schema are
unchanged. The default database location is repository-absolute, with an optional
`ECHOROLE_DB_PATH` override evaluated before startup.

FastAPI exposes typed Phase 1 contracts under `/api/v1`, retaining health and
public scenario catalog routes. See `backend/README.md` for all endpoint bodies,
responses, status codes, identity rules and startup commands. It never imports
Streamlit, AI, or RAG. Startup owns database initialization; import is side-effect
free. Public responses explicitly exclude private role briefs.

Streamlit remains the functional reference. Extracted workflows call the same
legacy persistence helpers in the same order, with its sync callback retaining
local event-version bookkeeping. Legacy active-member limits, role reservation,
role order, late assignment and session content are retained.

Phase 2 prerequisites:

- Choose durable authentication and identity recovery; Phase 1 API bearer tokens
  are local process memory and do not trust client-supplied legacy UUIDs.
- Choose browser forwarding/credential transport before interactive Next.js work.
- Address concurrent multi-transaction room/session writes and idempotency before
  multi-worker or shared external access; current persistence boundaries remain.
- Define caller-scoped private contracts before any private role or AI endpoint.

AI Coach, suggestions, chat, actions, turn advancement, story/progression
creation, peer feedback, WebSockets and frontend redesign remain deferred.
No merge, push or deployment is part of Phase 1. Local skill directories remain
unstaged; `.agents/skills/ui-ux-pro-max/` remains excluded locally.

Verification: `backend/.venv/Scripts/python -m unittest discover -s backend/tests -v`.
Tests use disposable databases, including a sqlite_master comparison against the
pre-change database implementation. Runtime verification results are recorded
below when completed.

Phase 1 verification (2026-09-11): all 12 backend tests passed. FastAPI and
Streamlit each started on loopback and returned HTTP 200, using disposable
SQLite files. Streamlit AppTest rendered the welcome page, executed Create Room,
and rendered the lobby without exceptions. Verification processes were stopped.
The schema matches baseline commit `460c149` and repeated initialization leaves
it unchanged. The existing `echorole.db` SHA-256 remained
`6C5FEB3A88FBE6A111D7D46B65C2162F506631816FAB09350FC9B85BC6414AD7`.
Next.js was not modified; no frontend build was needed. Full legacy AI/turn
interaction was outside this phase and was not exercised.
