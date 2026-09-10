# EchoRole FastAPI boundary — Phase 1

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
schema, initialization SQL, persistence helpers and transactions are preserved.

All paths below have prefix `/api/v1`:

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/health` | Process liveness |
| GET | `/scenarios`, `/scenarios/categories`, `/scenarios/{scenario_id}` | Existing public scenario catalog |
| POST | `/profiles` | `{display_name, mbti?, priorities?}`; creates UUID profile and returns bearer token (201) |
| POST | `/rooms` | No body; creates room and adds caller (201) |
| POST | `/rooms/{room_id}/join` | No body; joins caller, activating available role if a session exists |
| GET | `/rooms/{room_id}` | Public room metadata and event version; membership required |
| GET | `/rooms/{room_id}/members` | Ordered public member list; membership required |
| POST | `/rooms/{room_id}/sessions` | `{scenario_id}`; membership required; creates session and assigns roles (201) |
| GET | `/rooms/{room_id}/session` | Public current session, or JSON null in lobby; membership required |

Use `Authorization: Bearer <access_token>` for every room endpoint. Profile
creation never accepts a user ID. Tokens are random, held in this API instance,
and expire on restart; use a single local API worker. They do not authenticate
or restore legacy URL identities. Durable identity/recovery and browser transport
remain future work. No private role endpoint exists.

Responses use explicit allowlists; public session data excludes role briefs,
role perspectives, private coach content, and complete database records. Errors
use `detail`: 401 for missing/invalid identity, 403 for non-members, 404 for missing
rooms/scenarios, 409 for legacy capacity/role limits, and 422 for invalid contracts.

Session creation retains legacy latest-session semantics, including creating a
new session on another request. Roles follow membership order, role_a then role_b;
late arrivals receive the first vacant role, and returning participants retain
their assignment. Join checks retain both active-member and reserved-role limits.
Streamlit retains its URL restoration, UI feedback, sync callbacks and reruns.

This remains local Phase 1 infrastructure. Existing multi-transaction operations
are not atomic across concurrent callers/processes; concurrency/idempotency and
durable authentication must be settled before broader exposure. No permissive CORS,
AI routes, turn actions, WebSockets, or Next.js redesign were added.

Tests use disposable databases and compare sqlite_master against the original
initialization implementation. Install Streamlit and streamlit-autorefresh in the
legacy environment to run `python -m streamlit run app.py`; they are not backend
runtime dependencies.
