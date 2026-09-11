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


## Phase 4.5 — remaining functional parity

Continued from `1296f18` on `migration/nextjs-fastapi`. Both identified parity gaps
are closed without redesign, UI UX Pro Max, schema changes, external auth,
WebSockets, deployment or unrelated product features.

Peer feedback is available from turn 3 with another current assigned participant.
The shared Python service retains Streamlit's half-star choices, ten points per
star, one immutable rating per session/rater/recipient and cumulative received
points. Existing database helpers and unique indexes are reused. The Next.js UI
renders server-supplied choices/eligibility, its own saved private comment and its
own total score. Polling updates feedback/scores. Retry preserves original payload
and cannot duplicate points or room events. Streamlit calls the same service.
Typed FastAPI allowlists expose only the caller's feedback and score.

Initial profile creation now requires preparation. A signed enrollment credential
is saved in an HttpOnly cookie before any profile write; FastAPI atomically creates
or reads its fixed UUID. Preparation response loss produces no profile. Creation
response loss is recovered through that same credential, including after reload or
server restart. First successful payload wins; edited retries cannot overwrite it.
The client serializes enrollment across tabs with Web Locks. Enrollment cannot
access authenticated endpoints, and public UUIDs cannot claim profiles. Cookies
retain the existing 30-day lifetime and explicit clear-identity removes both.
Recovery after deletion/expiry of all credentials is intentionally not introduced.
No credential is put in browser JSON or JavaScript storage. No new database schema.

Verification: 45 backend tests (all previous 40 plus 5 parity/security/concurrency
regressions), Next.js production build and typecheck, live transport smoke,
two isolated Chromium contexts using a disposable database/local AI, and Streamlit
AppTest through turn-3 feedback submission and 45-point scoring. Browser testing
loses the initial profile response before retaining its identity cookie, reloads,
retries with edited input and verifies the same UUID plus exactly two rows for two
participants. Feedback response loss/replay awards points once; comments remain
isolated and score updates reach the recipient. Existing turn/recovery/chat flow
continues to pass. Test servers are stopped; no paid/external provider calls.

The scoped functional parity gaps are closed and the app is ready for visual
redesign. Production authentication/revocation/admission/HTTPS remain separate
from visual work. Phase 4.5 stops here; no push or merge.

Phase 4.5 changed files:
- `app.py`, `application.py`
- `backend/api.py`, `backend/identity.py`, `backend/schemas.py`, `backend/README.md`
- `backend/tests/test_stateful.py`, `backend/tests/test_parity.py`, `backend/tests/streamlit_smoke.py`
- `frontend/src/app/api/echorole/[...path]/route.ts`, `frontend/src/app/workflow.tsx`
- `frontend/src/lib/client.ts`, `frontend/src/lib/contracts.ts`
- `frontend/tests/transport_smoke.py`, `frontend/tests/ui_smoke.cjs`, `frontend/README.md`
- `docs/migration-nextjs-fastapi.md`

## Landing visual pass

Continued from `290468b`. Only the entry screen is restyled, using the local
UI UX Pro Max guidance and the supplied cream/sage editorial reference. The new
`landing.tsx` and scoped CSS module preserve the existing workflow callbacks,
profile-first sequence, enrollment recovery, and room retry payloads. Lobby and
Active Session retain their previous markup and global styles. No backend or API
files changed. The original logo is copied unchanged into Next.js public assets.

Temporary code-native art slots are marked `hero`, `character`, `doorway`, and
`invitation`; final illustrations are deferred. Text and controls remain HTML.
Verification includes build/typecheck, entry layouts at 375/768/1024/1440px,
profile fields/edit/reload, identity lost-response recovery, and the existing
two-browser room/session smoke. Local preview uses separate temporary SQLite data.

## Lobby and scenario setup visual pass

Continued from `679141b`. The preparation room now uses the approved landing's
cream/sage tokens, editorial typography, thin surfaces, and doorway motif.
`editorial.tsx` extracts the identical Brand, Arrow, and Doorway markup for reuse;
landing styles remain unchanged. `lobby.tsx` is a presentational view with scoped
CSS, scenario-first hierarchy, participant presence, secondary shared chat,
collapsed profile editing, and explicit loading/update-retry states. Scenario
text comes unchanged from the API. Active Session markup, backend behavior,
polling, identity, authorization, and mutation request handling are preserved.

Verification: production build and typecheck; 45 backend tests; Streamlit smoke;
two independent Chromium contexts against a disposable database and local AI.
Lobby checks cover join/leave polling, profile editing, shared chat, every
category and exact preview content, session creation, loading and failed-update
recovery, and 375/768/1024/1440px layouts without overflow. Existing identity
recovery, private/shared separation, retry, turn, and feedback checks still pass.
Desktop/mobile screenshots were reviewed. No final illustration assets added;
the reusable CSS doorway remains a temporary illustration. Stop at Lobby / Setup.

## Active Session visual pass and stale local identity recovery

Continued from `636ca86`. Landing and Lobby remain the approved visual source of
truth and their components/styles are unchanged. Active Session now uses a
narrative-centered composition, quiet context, a private brief and Coach notebook,
secondary private guidance, a clear action/waiting area, warm shared chat, and
compact progression disclosures. Existing Brand and landing tokens are reused in
`active-session.tsx` and its scoped CSS. At 1024px context moves below the main
workspace; at 768px and below the scene, brief, action, guidance, Coach, chat, history,
feedback and utilities stack in that order. No second design system or final art.

Rejected upstream identity credentials now carry a `stale_identity` error code so
startup can distinguish them from a first visit. The explicit "Start with a new
profile" action uses the existing same-origin DELETE identity handler to expire
both HttpOnly cookies, clears tab identity/session/retry state, and restores normal
profile creation. No identity validation, FastAPI, Python services or schema changed.
Valid identities and lost-response enrollment recovery are retained.

Verification: production build and typecheck; 45 backend tests; live transport
smoke (HttpOnly, CSRF, membership, isolation and retry); two independent Chromium
contexts with disposable data/local AI. Browser checks cover exact private-role
separation, Coach, suggestions, shared chat, stable retries after response loss,
action waiting and real joint advancement, history, feedback, reload and leave.
Generating/uncertain presentation uses controlled response fixtures; explicit
acknowledgement and fenced recovery payloads are checked, while durable generation
and recovery are covered by backend tests. Deleted-profile regression verifies
401 -> explicit reset -> cookies/tab state cleared -> new UUID -> room/reload,
with an existing valid participant unaffected. Layouts at 1440/1024/768/375px have
no horizontal overflow. No shared Python changed, so Streamlit smoke was not rerun
for this pass. No push, merge, global polish, or additional page redesign.

## Global UI polish

Continued from `8f4fa84`; all three approved layouts and information priorities
are retained. Shared foundations now live in `theme.css`: palette, typography,
control radii, focus, feedback surfaces, soft shadow and reduced-motion rules.
`Feedback` and `ConnectionNotice` replace repeated page-specific presentation.
Offline messaging observes browser connectivity only and never retries mutations.
Small text contrast, placeholder readability, 44px controls, skip-link focus,
scenario reading measure, mobile footer wrapping and destructive utility tone
were refined. Loading dots and keyed message/scene fades are restrained and fully
disabled by reduced-motion preference. Cleared message composers deliberately do
not receive invalid styling after successful submission. Empty/recovery copy is
clarified without rewriting scenarios, AI content or recovery requirements.

Verification: production build/typecheck, 45 backend tests, live transport smoke,
and the complete two-context browser suite including identity reset, privacy,
polling, retry, Coach, shared messages, actions, waiting, progression, peer feedback,
reload and leave. Generating/uncertain UI remains fixture-tested alongside backend
recovery tests. All pages are captured at 1440/1024/768/375px without overflow.
Added practical browser checks for visible text contrast (excluding decorative and
disabled content), labels, control target height, keyboard focus, skip destinations,
reduced motion and offline/online presentation. Screenshots were visually reviewed;
this is not a screen-reader certification. Final illustration slots remain temporary.
No backend, API client, authorization, polling or mutation logic changed. No push,
merge or deployment.
