# Next.js + FastAPI migration — Phase 3

Phase 1 (`824a4f3`) and Phase 2 (`7003770`) are complete. Phase 3 continues on
`migration/nextjs-fastapi`; no merge, push, external infrastructure or Next.js visual
redesign is part of this work. `.agents/skills/ui-ux-pro-max/` stays local only.

The user explicitly approved the minimum SQLite schema change needed for durable
claims/recovery and made the local database disposable. This supersedes the earlier
schema freeze for this phase. Tests still use temporary databases and do not alter
the existing application database.

## Architecture and scope

```text
Next.js same-origin server handlers -> FastAPI routes
                                          |
Streamlit app.py -----------------> shared services
                                   application.py / interaction_service.py
                                          |
                       database.py / operation_store.py / ai_engine.py
                                          |
                              existing scenarios / RAG
```

FastAPI never imports `app.py` or the diagnostic `ai_messages.py`. AI/RAG are loaded
lazily only when needed; health/import does not initialize them. Routes only validate
contracts, resolve Phase 2 authorization and call services. Both UIs use the same
chat, Coach, role context, action and joint-generation orchestration.

Implemented: room-shared chat; own private brief/history/pressure; own Coach
messages and durable request state; own suggestions; action submission and status;
joint story generation, atomic advancement and public progression history. Peer
feedback remains in Streamlit; no new peer-feedback API or visual redesign was added.
See backend/README.md for every route/body/status and frontend/README.md for transport.

## Identity, transport and authorization retained

Phase 2 signed 30-day tokens use the persistent local signing key and existing
profile UUIDs. Browser tokens remain host-only HttpOnly/SameSite=Strict cookies.
Next.js forwards bearer credentials server-side, strips tokens from browser JSON,
requires the configured mutation Origin, and disables caching. Secure cookies are
default; loopback HTTP development explicitly opts out. No external auth provider.
Cookie loss/expiry has no unverified UUID-based recovery; local sign-out does not
revoke stolen copies. Real authentication/revocation/HTTPS are still required before
external exposure.

Every session route requires current room membership plus role ownership in that
exact session. Private reads are scoped to the authenticated participant, never a
body-supplied user/role. The explicit role URL also requires the role-owner dependency.
Only that participant sees their Coach messages, brief history, pressure and
suggestions. Shared APIs use typed allowlists and omit private payloads, raw journal
records and other participants' pending actions. Shared chat stays room-scoped and
ordered by insertion ID; Coach messages remain participant/session/turn-scoped.

## Minimal additive schema

Only one new table, `operation_journal`, is introduced. The primary operation key
identifies a room chat request, a participant Coach request, or a session+turn.
Columns store operation kind/scope, participant/turn, state, unique attempt token,
start time, immutable captured inputs, generated result and a sanitized error.
States are `running`, `ready`, `completed`, `uncertain`. The table contains sensitive
context and must not be served directly.

All old tables and indexes remain unchanged. Existing unique indexes already cover
membership, role allocation, per-participant/role turn actions, turn history,
story state and suggestions. Startup initialization adds the table idempotently.
Tests compare every old sqlite_master entry against the baseline and exercise an
in-place legacy upgrade with data preserved. Stop old Streamlit/API processes before
upgrading; old binaries do not implement the new fencing protocol.

## Retry and completion protocol

- Chat/Coach requests use caller-generated `request_id`, scoped to room/session and
  authenticated user. Same ID+payload replays the result; changed content/turn is 409.
  Different IDs intentionally create separate messages. Chat insert, attribution,
  event version and replay result commit in one transaction.
- One accepted action per participant per turn is immutable, matching the legacy
  disabled submission form. Same-text repeats are safe. An exact completed-action
  replay returns `advanced`; other stale/future actions are rejected. Session
  replacement is blocked while actions remain pending/generating.
- Once both valid actions exist, `BEGIN IMMEDIATE` and the unique turn operation key
  let one caller create a durable claim and freeze its generation inputs. No Python
  process lock is used for correctness. Provider calls run outside SQLite transactions.
- A successful generated result is persisted as `ready` with its attempt token.
  Another short transaction reuses `complete_joint_turn` and the existing unique
  indexes/current-turn compare-and-swap. It commits history, story, both private
  suggestions, private action records, consumption, event version, turn advancement
  and journal completion together. Any failure rolls all these writes back.
- Retrying a ready result persists it without invoking AI again. Concurrent callers
  can complete it once; later requests see `advanced`/`completed`. Repeated Coach
  requests similarly avoid duplicate user/reply rows and serialize unfinished
  conversations per participant. Own request-list/status endpoints recover IDs after
  a browser interruption.
- Exceptions/empty outputs, transport loss or server errors observed even through
  legacy fallback, and claims older than 15 minutes become `uncertain`. Age alone
  never starts another provider call. Legacy `generating` actions without a journal
  also become uncertain instead of being silently retried.
- Recovery explicitly requires the current attempt token plus
  `acknowledge_uncertain: true`. It fences the old attempt and generates from the
  original captured inputs. A late old response cannot replace the new result.
  Normal retries do not regenerate. Acknowledged recovery may repeat external work:
  no provider-supported exactly-once external invocation is claimed. Database turn
  completion/advancement is exactly once, including after recovery.

## AI and Streamlit compatibility

Prompt templates, model/provider selection and RAG logic are unchanged. A tiny
request-local transport observer marks uncertain outcomes; it does not consult the
shared debug snapshot or expose provider details. Existing local/missing-key fallback
continues to work; network uncertainty is surfaced rather than silently accepted.

Coach history filtering and text normalization moved verbatim from Streamlit into
`coach_context.py` (UI filter logging excluded). Coach context uses the same profile,
current situation and recent history captured before adding the new user message.
Joint generation uses the same legacy generator and result fields. Both evolved
role briefs are assembled deterministically, removing the legacy dependence on
which participant happened to run generation. Suggestions are generated with the
joint result for the next turn; no separate suggestion prompt was invented. An
initial turn can legitimately return an empty suggestion.

Streamlit's existing layout remains. Submission/Coach/chat entry points now call
shared services; old UI-bound generation/persistence branches are removed. Explicit
uncertain-recovery controls were added. Another participant's pending action text
is no longer displayed; submission flags and one's own action remain visible.
These are the intentional privacy/concurrency changes required for safe API semantics.

## Verification and remaining frontend work

39 backend tests pass, retaining Phase 1/2 regressions and adding chat/Coach isolation,
private role authorization, action/retry/stale checks, thread/process competition,
single provider execution on the normal path, exactly-once advancement, rollback,
saved-result replay, expired/legacy claims, late-worker fencing, explicit uncertain
recovery and additive legacy schema upgrade.

Next.js production build and typecheck pass. Live Next.js/FastAPI transport tests
pass for cookie/restart recovery, CSRF, chat retries, private role/Coach isolation,
action waiting/completion, progression and suggestions, using the local provider.
FastAPI and Streamlit start on loopback. Streamlit AppTest exercises welcome,
room/scenario setup, shared chat, private Coach, first-action waiting, second-action
joint advancement and evolved brief/suggestion rendering without exceptions.
No paid/external AI provider requests were made during verification.

The existing database SHA-256 remains
`6C5FEB3A88FBE6A111D7D46B65C2162F506631816FAB09350FC9B85BC6414AD7`.
Verification processes are stopped after tests. No push or merge.

Before connecting the full Next.js frontend, implement the visual session screens,
polling and typed status handling, stable client request IDs, and explicit recovery
acknowledgement. Do not turn transport timeouts into automatic recovery. Production
exposure still needs real auth/revocation, an admission policy and HTTPS. No other
infrastructure is required for this local-development Phase 3 foundation.

## Phase 4 — functional Next.js frontend

Continued from `d9a9c94` on `migration/nextjs-fastapi`. The complete requested
API-backed flow now runs on `/`, with plain functional sections and no final visual
redesign. UI UX Pro Max was not used; its local files remain uncommitted.

Implemented profile creation/editing, create/invite join, lobby/member updates,
scenario filtering/preview/setup/replacement, active shared situation, own private
brief/history/pressure/decision point, private Coach/messages/request recovery and
suggestions, shared chat, immutable actions, waiting/generation/explicit uncertain
recovery, turn advance, progression history and leave/rejoin. No peer-feedback API
was invented; that Streamlit-only functionality remains outside this phase's flow.

Typed browser contracts/client are separate from server transport. Polling runs
non-overlapping cycles every 2.5 seconds after completion, pauses when hidden,
and resumes on visibility/online/manual refresh and mutations. Identity/room epochs
fence late responses and mixed-turn snapshots are retried. Private projections are
never written to browser storage. Saved outbound retry payloads are private to the
tab and participant; see frontend/README.md for retention and identity limitations.

Chat/Coach use saved UUID request IDs; room creation gains atomic deterministic
request replay without schema changes. Session setup retains original expected
session ID and scenario; actions retain original turn/text. Recovery always needs
explicit acknowledgement/current attempt; transport timeout never regenerates AI.
Natural state operations retain idempotent semantics. First-profile response loss
before receipt of the HttpOnly cookie can still orphan a profile; no credential
recovery shortcut was added.

Verification: production build and TypeScript check; 40 backend tests; real
Next.js/FastAPI transport smoke; Streamlit active-session smoke; two isolated
Chromium contexts with the local provider and disposable data. UI coverage includes
private role/Coach separation, shared chat response loss plus reload/replay producing
one message, first-action waiting, second-action advancement to turn 2, progression,
refresh restoration and leave/member polling. Uncertain UI acknowledgement/payload
uses a controlled browser response fixture; durable uncertainty/fencing remains
covered by backend tests. No paid AI calls, push, merge or deployment.

Before visual redesign: agree on whether a later functional scope should expose
Streamlit peer feedback/points. The requested Phase 4 flow is otherwise available.
Production identity/revocation/admission/HTTPS work remains separate from visual work.
