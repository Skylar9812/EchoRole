# Next.js + FastAPI migration skeleton

Base: stable commit `64c66db`. Branch: `migration/nextjs-fastapi`. The existing `ui/immersive-redesign` branch is preserved; no merge or push is part of this setup.

## Scope established

```text
frontend/ (Next.js + TypeScript)
    -> server-side HTTP request
backend/ (FastAPI, /api/v1)
    -> legacy adapter
scenario_library.py (unchanged)
```

The frontend is an unstyled development landing page with an API health check. The backend provides liveness and read-only public scenario previews. All stateful migration remains deferred. No placeholder mutation endpoints, mock rooms, new features or UI design have been added.

`app.py`, `database.py`, `ai_engine.py`, `ai_messages.py`, `rag_engine.py`, `scenario_library.py`, `assets/`, `rag_docs/`, `rag_index/`, and `echorole.db` remain in their original locations. Streamlit remains the functional reference and can still be launched from the repository root with its existing environment: `python -m streamlit run app.py`.

`docs/frontend-ui-audit.md` is preserved. The existing local skill directory is preserved and excluded only through this checkout's `.git/info/exclude`:

```text
.agents/skills/ui-ux-pro-max/
```

Do not stage, commit, push, or copy the skill into either application. This exclusion is local to the checkout and does not propagate to new clones. The skeleton does not use the skill. Existing unrelated local skills are also left untouched and unstaged.

The accidental empty root `package-lock.json` was removed. The new frontend owns `frontend/package.json` and `frontend/package-lock.json`; there is no root JavaScript workspace.

## Proposed API boundaries for the next phase

Only the first two rows below are implemented. Paths in other rows are proposals, not available endpoints.

| Boundary | Candidate HTTP contract | Existing code to reuse / behavior to preserve |
| --- | --- | --- |
| Liveness | `GET /api/v1/health` | No database or AI initialization. |
| Scenario catalog | `GET /api/v1/scenarios`, `/scenarios/categories`, `/scenarios/{id}` | Existing scenario helpers; public fields only; content unchanged. |
| Identity/profile | `GET/PATCH /api/v1/me` | Profile read/save functions; trusted identity required before implementing. |
| Rooms/membership | `POST /api/v1/rooms`, `POST /api/v1/rooms/join`, `GET /api/v1/rooms/{id}`, `DELETE /api/v1/rooms/{id}/members/me` | Create/join/leave, capacity checks and event-version bumps in their existing order. |
| Scenario session | `POST /api/v1/rooms/{id}/sessions`, `GET /api/v1/sessions/{id}` | Existing session creation, role assignment and shared story state. Never return full DB records. |
| Private role view | `GET /api/v1/sessions/{id}/me/briefs` | Caller-scoped role, pressure, private brief history and suggestions. |
| Private coach | `GET/POST /api/v1/sessions/{id}/me/coach/messages` | Existing prompt creation, visible-history filtering, AI generation and message persistence. Preserve RAG and prompt behavior. |
| Shared chat | `GET/POST /api/v1/rooms/{id}/messages` | Existing room-scoped chat persistence; do not silently change it to session scope. |
| Turn action/status | `POST /api/v1/sessions/{id}/turns/{turn}/actions`, `GET /api/v1/sessions/{id}/turns/{turn}/status` | Existing validation, pending actions, atomic generation claim, completion and retry/stale-turn handling. |
| Progression/history | `GET /api/v1/sessions/{id}/history` | Existing shared progression with separate role-private content. |
| Peer feedback | `GET/POST /api/v1/sessions/{id}/me/peer-feedback` | Existing turn eligibility, star-to-point mapping and per-session feedback rules. |
| Synchronization | `GET /api/v1/rooms/{id}/events/version` | Existing event versions and polling semantics. No WebSocket/event redesign yet. |

AI and RAG remain implementation details behind domain routes; do not expose an unrestricted prompt or retrieval endpoint.

## Architecture issues to resolve before stateful implementation

1. **Streamlit orchestration is not an importable service.** `app.py` initializes the database and executes UI code at import time. Room/role setup, coach persistence, validation feedback and joint-turn orchestration are mixed with session state and reruns. Do not import it into FastAPI or copy those flows into a second implementation. Plan a carefully tested shared service extraction in a later phase while keeping Streamlit as a caller/reference.
2. **Identity and authorization.** The current UI restores UUID/name/room values from URL/session state. That is not an authenticated HTTP identity boundary. Decide a trusted identity mechanism and enforce membership plus role ownership before exposing room/private endpoints. A client-supplied `user_id` must not select another user's private brief/chat.
3. **Data path and lifecycle.** `database.DB_NAME` is relative (`echorole.db`). API processes launched from another directory could create/read a different file. Root-based launch is explicit here, and no DB import/init occurs. Decide one absolute database path and startup ownership before writes; preserve schema and existing transactions.
4. **Concurrency and exactly-once turn completion.** API requests, polling and Streamlit can overlap. Reuse pending-action claims and `complete_joint_turn`; retain stale-turn and retry rules. Define request idempotency and SQLite lock handling before wiring mutation routes.
5. **Blocking AI/RAG and shared globals.** Existing provider configuration/debug snapshots and RAG caches are process-global; AI calls are synchronous. Define request-scoped diagnostics and an execution strategy before concurrent coach/generation requests. Do not change prompts/provider selection or RAG behavior in the skeleton.
6. **API DTOs and synchronization.** Legacy helpers return tuples/dicts containing both shared and private fields. Explicitly model caller-specific responses, status/error semantics and event-version polling. Avoid serializing database records directly.
7. **Browser integration.** Server-to-server health fetching needs no CORS. Before interactive forms, choose same-origin Next.js forwarding or explicit FastAPI origins/authentication, and keep credentials server-side. No permissive CORS or public mutation access is enabled now.

## Verification commands

From the root, after installing backend development dependencies:

```powershell
python -m unittest discover -s backend/tests -v
```

From `frontend/` after `npm ci`:

```powershell
npm run build
npm run typecheck
```

Contract tests cover health, unchanged scenario content, category filtering, 404s, omission of private role fields, side-effect-free imports and absence of stateful routes. No test opens the application database or calls an AI provider. See each application's README for startup commands.

Setup verification on 2026-09-10: four API tests passed; `npm run build` and `npm run typecheck` passed. Local HTTP checks returned all 11 legacy scenario previews and a Next.js 200 response with FastAPI status `Available`. Verification servers were then stopped. The legacy source diff against `64c66db` is empty; database, audit and local skill-file hashes were unchanged. No browser/design verification was performed or needed for this development skeleton.
