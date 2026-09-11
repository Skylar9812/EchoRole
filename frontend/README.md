# EchoRole Next.js frontend — Phase 4.5

Plain functional UI; visual redesign is deferred. The `/` page implements profile
creation/editing, create/join by invite code, lobby/members, scenario category and
preview/setup/replacement, active situation, own role brief/history/pressure,
private Coach/history/suggestions, shared chat, action submission, waiting and
joint advancement, shared progression history, turn-3 peer feedback, cumulative peer points, and leave/rejoin.

## Run

Start FastAPI as described in `backend/README.md`, then:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Open `http://127.0.0.1:3000`. The exact browser origin must match
`ECHOROLE_WEB_ORIGIN`. `ECHOROLE_API_URL` is server-only. Loopback HTTP requires
`ECHOROLE_COOKIE_SECURE=false`; Secure cookies remain the default otherwise.

## Boundaries

`src/lib/contracts.ts` contains browser-safe response/request types;
`src/lib/client.ts` centralizes typed same-origin calls and error handling.
`src/lib/api.ts` is server-only FastAPI transport. The Next.js route handler uses
an explicit allowlist, validates mutation Origin, forwards only its HttpOnly
identity cookie as a bearer credential, strips tokens from browser responses,
and disables caching. Python services retain all role, validation, generation,
capacity, privacy and turn rules. React renders server state.

Private briefs, Coach replies and suggestions stay in component memory and are
cleared on room/identity changes. Shared views never receive a peer's private data.
Only pending outbound payloads (including one's own Coach input/action) are kept
in participant-scoped sessionStorage for retry after reload. They are removed on
confirmed success or explicit discard; clearing identity removes all saved retries.
The selected room is tab-scoped. Cookies remain HttpOnly, never in JS storage.

## Polling and consistency

A single non-overlapping refresh reads room, members, public session and shared
messages, then own private/Coach/request/suggestion/turn/history projections.
Polling schedules the next refresh 2.5 seconds after the previous cycle finishes,
pauses while hidden, and refreshes on visibility/online events and after mutations.
A manual refresh button is always available. No WebSockets or automatic AI recovery.
Room/identity epoch fencing discards obsolete responses. Mismatched turn snapshots
are not published; the next cycle retries. Failures display a stale-data warning
and disable new submissions. 401 clears private state and requires local identity
reset; 403 clears the room snapshot. 409 explains stale/conflicting state.

## Retry strategy

- Chat and Coach: `crypto.randomUUID()` per logical message, with original payload
  saved before sending. Retry uses the same ID and content, never the edited draft.
- Room creation: a saved UUID feeds a participant-scoped deterministic 24-character
  invite code. Atomic create/replay requires membership and needs no new schema.
  Legacy calls without an ID retain the original random six-character code.
- Scenario setup/replacement: save original scenario and expected session ID;
  retry reuses that compare-and-swap contract even after polling sees a new session.
- Actions: save immutable original session/turn/text; Python's existing unique
  participant/turn action is the idempotency key. No invented frontend action rules.
- Join, leave, profile update and local sign-out use their existing/natural state
  semantics. Profile creation uses the two-step enrollment protocol below.
- The unconfirmed-request panel survives reload, offers exact replay and explains
  discard risk. Validation (422) frees the draft to be corrected. Transport failure
  does not establish whether the server committed or the provider finished.

Coach running/ready/uncertain requests are recovered from the server request list.
Ready replies have a save button without another provider call. Both Coach and
turn uncertainty show an acknowledgement checkbox and require the current attempt
ID. Recovery warns that external AI work may repeat; ordinary polling never calls
recovery. Turn completion can safely resume a saved result using the existing API.

## Verification

```powershell
npm run build
npm run typecheck
# From repository root:
backend/.venv/Scripts/python -m unittest discover -s backend/tests -v
backend/.venv/Scripts/python frontend/tests/transport_smoke.py
backend/.venv/Scripts/python -m backend.tests.streamlit_smoke
node frontend/tests/ui_smoke.cjs
```

The UI smoke uses two isolated Chromium contexts against temporary SQLite and the
local AI provider. Set `ECHOROLE_PLAYWRIGHT` to an installed Playwright module and
`ECHOROLE_CHROMIUM` to an existing Chromium executable if the default installation
is unavailable. It starts loopback ports 3317/8317 and stops its own servers.
It covers the real rendered flow, private isolation, lost-response replay after
reload, turn advance, room restoration and leave polling. A mocked uncertain
response separately verifies the checkbox and recovery payload; backend tests
verify actual durable recovery/fencing. No external AI calls are needed.

## Phase 4.5 peer feedback and enrollment

Peer feedback opens from turn 3 with another active assigned participant, exactly
as in Streamlit. Python returns eligibility, target, half-star options and point
values. The shared service uses the existing database normalizer and unique
session/rater/recipient constraint: one immutable rating per pair per session,
0.5–5 stars, ten points per star, summed across sessions for the recipient.
Comments and saved ratings are readable only by their author; the score endpoint
returns only the authenticated participant's total. Polling updates scores and
feedback status. Saved outbound feedback retries survive reload and reuse the
original session/recipient/payload, without another award or event-version bump.
Streamlit submits through the same service and retains its presentation.

Before initial creation the typed client calls `POST /api/echorole/profiles/prepare`.
This stores a signed, random, purpose-separated enrollment credential in an
HttpOnly/SameSite=Strict/host-only cookie; Secure is the default. Preparation has
no database writes. Only after that response succeeds does the client POST the
profile. The server forwards the enrollment credential to FastAPI, which atomically
creates or returns its fixed UUID. The first successful payload wins; retries with
edited fields return the original/current profile, never overwrite it. Use profile
editing after recovery to change fields. Browser JSON and JS storage contain neither
identity nor enrollment credentials. Web Locks serialize preparation/creation across
tabs; loopback/HTTPS browsers must support Web Locks. No external auth is introduced.

The enrollment cookie is retained for the existing 30-day identity window, so a lost
profile response (even before its identity cookie arrives), reload, or server restart
can recover the same profile. Loss of the prepare response creates no profile and is
safe to repeat. Missing preparation is 428 in Next.js; invalid/expired enrollment is
401 in FastAPI. Clearing local identity clears both cookies. Explicit cookie deletion
or expiry still ends recovery; no public UUID or display name can claim an account.

Verification adds lost-profile-response browser replay with a database row-count
assertion, feedback retry without duplicate points, private-comment isolation,
concurrent initial enrollment and restart replay, and real Streamlit feedback.
Both Phase 4 parity gaps are closed. Real authentication, revocation, admission
policy and HTTPS remain separate prerequisites for external exposure.
