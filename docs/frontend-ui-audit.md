# EchoRole frontend audit

Date: 2026-09-09. Scope: source inspection only; no application UI or business logic changed. Visual findings below are code-derived, not browser-verified. The default Python executable could not launch, so no live Streamlit rendering was tested. No repository AGENTS.md was found.

## 1. Frontend inventory

| File / location | Responsibility |
| --- | --- |
| `app.py:68` | Streamlit page configuration (`layout="wide"`, page title); no explicit favicon. |
| `app.py:224–515` | Logo loading, global CSS injection, active-session CSS override. |
| `app.py:517–954` | Role labels, header, text/profile/room/member cards, profile editor, progression history, suggestions, private briefs, situation, overview, star rating, peer feedback, coach context. |
| `app.py:1022–1138` | AI message presentation mixed with filtering and render diagnostics. |
| `app.py:1373–1780` | Turn-generation status/error presentation, validation feedback, and submit lifecycle intertwined with orchestration. |
| `app.py:1783–1982` | Session-state initialization, style activation, URL restoration, refresh constants; these affect routing and UI lifecycle. |
| `app.py:1985–3603` | All page composition, widgets, submission handlers, loading/waiting/error states, room controls and refresh scheduling. |
| `assets/echorole_icon.png` | Existing raster brand logo; retain as the branding source of truth. |
| `scenario_library.py` | UI-facing scenario categories, titles, context, conflict, opening situation and private briefs; content/data dependency, not a layout module. |
| `ai_engine.py`, `ai_messages.py`, `database.py`, `rag_engine.py` | Supporting generation, message semantics, persistence and retrieval. No direct Streamlit/CSS/HTML rendering found outside `app.py`; preserve these contracts. |

No standalone CSS/HTML files, Streamlit `pages/` directory, or project `.streamlit/config.toml` was found. No Python dependency manifest or UI test suite was found. `check_history.py` is a diagnostic script, not a page. RAG documents and scenario specifications are content inputs, not frontend implementations. The pre-existing untracked `package-lock.json` is not referenced by the Streamlit frontend.

## 2. Current page/state map

The five conceptual steps are implemented as **three layouts**, not five separate pages.

| State and condition | Major sections | Transition |
| --- | --- | --- |
| Welcome: `room_id is None` (`app.py:1985`) | Brand header; left profile inputs (display name, MBTI, priorities); right create-room and join-room cards. Columns `1.08 : 0.92`. | Create/join validates and saves identity/profile, updates room state and URL, then reruns. Profile setup is not a separate saved wizard step. |
| Lobby + scenario setup: room exists, `current_session is None` (`app.py:2120`) | Header with room code; left profile/editor, room information, members, refresh/leave controls; right category/title selectors, scenario preview, create-session action, shared chat. Columns `1.02 : 1.38`. | Create scenario session, assign available members to roles, bump sync event and rerun. There is no separate readiness-confirmation page or two-member launch gate in this branch. |
| Active session: room and session exist (`app.py:2212`) | Header; three-column dashboard `1.05 : 1.8 : 1.22`. | Valid actions from both participants trigger joint story generation and advance the turn. Leave clears room-specific state and returns to welcome. |

Active dashboard sections:

- **Left:** profile/editor, room code and user ID, members, scenario overview/current turn, peer rating/comment, refresh and leave.
- **Middle:** current situation, conditional private pressure and shared next decision, private role-brief history, AI coach messages, optional debug expander, AI reply form, reflection prompt and progression history.
- **Right:** private AI suggestion, turn-action form, validation and submission status, other participant's available action, waiting/generation feedback, reload, shared role-play chat.

Additional substates include unassigned role/session capacity errors, empty chat/history, missing peer, saved peer feedback, AI reply in progress/failure, action validation failure, waiting for the other action, story generation, and stale-turn reload. No distinct completion/results screen was found. URL restoration can enter an existing room directly. Lobby/idle refresh intervals are 5 seconds and pending-turn refresh is 4 seconds, with polling disabled during AI submission (`app.py:1977`, `3154`, `3573`). Preserve these behaviors during extraction.

## 3. Styling and brand

`inject_readability_styles()` (`app.py:235`, called at `1808`) injects a large `<style>` block through `st.markdown(..., unsafe_allow_html=True)`. It combines CSS variables, global Streamlit widget overrides and custom `.echorole-*` classes. Native `st.container(border=True)`, columns, forms and expanders supply the layout; HTML supplies the header, kickers, room-code badge, user ID, situation and rating visual. There is no iframe-based HTML layout.

Brand definitions:

- Logo path and base64 data URI: `get_echorole_logo_data_uri()` at `app.py:224`; image markup and alt text: `render_app_header()` at `527`.
- Green tokens at `app.py:242`: accent `#7D9A86`, strong `#668473`, soft `#E8F0E8`; green borders `#D8E1D5` / `#C7D3C4`.
- Additional hardcoded green treatments: button gradient `#8DA99B → #769281` (`347`), logo/badge shadows and borders, header accent gradient (`418`), situation border/shadow (`457`). These CSS values are not necessarily the exact colors embedded in the PNG.
- Current visual language: cream background, pale translucent surfaces, large rounded cards, pill buttons, generous text and green shadows. Typography, spacing, radii and elevation are mostly literals rather than tokens.

## 4. Issues and code smells

| Priority | Finding / evidence | Implication |
| --- | --- | --- |
| High | Optional HTML interpolations inside the header's multiline Markdown template (`562–578`). | Likely literal closing-tag leakage; see diagnosis below. |
| High | All button types receive the same green gradient, white text and shadow (`340–350`). No explicit interaction-state system. | Create/send, refresh and leave compete visually; disabled/focus/hover treatments need verification. White text against these light greens also warrants contrast measurement. |
| High | Star preview emits back/front layers (`829–854`), but CSS only styles the back color and rating metadata (`496–497`). | Missing positioning, clipping, no-wrap and foreground styling means the intended fractional overlay is not implemented; likely two stacked star rows. |
| Medium | Three dense columns, 96vw width, fixed 2rem horizontal padding, no custom media queries. | Narrow displays risk cramped panels; wide displays risk long reading lines. Streamlit's own stacking behavior must be checked on the installed version. |
| Medium | Full brand hero and many equally elevated cards; profile/room metadata repeated across header and rail. | Session focus and the next action compete with administrative information. Long briefs/history push the AI composer down the page. |
| Medium | Shared chat uses plain Markdown lines; AI replies use `st.info`; timestamps are read but not displayed. | Weak conversation hierarchy and inconsistent message treatment. Private/shared distinctions rely heavily on copy and position. |
| Medium | Broad `data-testid`, BaseWeb, child selectors and `!important` rules. | Streamlit DOM changes can silently break styles; native theme configuration is absent. The surface token exists but repeated literal surface colors remain. |
| Medium | `render_recent_progression_history_card` defined twice (`699`, `719`). | Second definition silently replaces the first; dead implementation obscures maintenance. |
| Medium | Shared-chat renderer and submit logic duplicated (`3466`, `3506`). | Lobby and session behavior can drift. These branches are mutually exclusive, so the repeated form key is not currently a same-run collision. |
| Medium | Render functions save profiles/feedback and trigger reruns; active layout contains extensive generation, database and debug logic. | Visual edits can accidentally alter side effects, form lifecycle or synchronization. |
| Low | `render_current_turn_card` and `render_ai_coach_context_cards` have no call sites; active CSS repeats global width settings. | Unused helpers and redundant overrides complicate the intended component model. |
| Low | Many section titles are bold paragraphs or `<div>` elements rather than semantic headings; mojibake exists in comments. | Navigation/accessibility and source readability need cleanup. |

### Likely raw HTML leakage mechanism

In `render_app_header`, absent `room_code_markup` and `supporting_markup` leave whitespace-only lines inside an otherwise indented HTML string. Welcome uses both defaults. Markdown HTML blocks can terminate at blank lines; subsequent indented closing tags can then be parsed as code and displayed literally. Streamlit's common-indent cleanup does not necessarily remove the remaining nested indentation. `unsafe_allow_html=True` permits HTML but does not bypass Markdown parsing.

This is a strong source-level hypothesis, **not a reproduced browser finding**. The template's tags appear balanced; there is no observed standalone `st.write("</div>")` call. Other multiline HTML renderers should be included in the reproduction check. The situation renderer deliberately escapes body text, so literal tags originating in that content would be displayed as text for a different reason.

Next step: render the header with neither optional field, each field individually, and both fields. Build complete HTML fragments without blank optional lines or Markdown-significant indentation. Use `st.html` only after verifying support in the installed Streamlit version; otherwise emit a compact, complete HTML string. Keep dynamic values escaped. Do not strip closing tags from content or open an HTML wrapper in one Streamlit call and close it around native widgets in another.

## 5. Proposed file-by-file frontend refactor

All paths below are proposals; this audit creates only this report. Keep imports one-way: app → views/components → theme/helpers; UI modules must not import `app.py`.

| File | Proposed responsibility / extraction |
| --- | --- |
| `app.py` | Retain bootstrapping, existing state predicates, data loading, URL state, validation, persistence, role assignment, AI orchestration and refresh scheduling. Gradually replace markup/widget construction with calls that return interaction values. Preserve handler execution order. |
| `ui/__init__.py` | UI package boundary. |
| `ui/theme.py` | Asset paths, semantic colors, typography, spacing, radii, shadows, content widths and one style loader. Preserve existing brand greens first. |
| `ui/styles.css` | Custom component styles and a small documented Streamlit compatibility section. Centralize primary/secondary/destructive, focus, disabled, error and waiting treatments; remove duplicated dashboard width injection. |
| `.streamlit/config.toml` | Supported native theme defaults aligned with the same palette; document/check parity with CSS rather than maintaining accidental divergent values. Confirm Streamlit version first. |
| `ui/components.py` | Header, section/card shell, room-code badge, metadata, situation, empty/status presentation and rating preview. Complete escaped HTML fragments only. |
| `ui/profile.py` | Profile/member display and profile form rendering. Return submitted values; retain existing save and membership-update handler in the controller. |
| `ui/chat.py` | Reusable shared-chat display/composer and separate private coach presentation. Preserve keys, placeholders and current message filtering; leave persistence and AI calls in existing orchestration. |
| `ui/scenario.py` | Scenario picker/preview, overview, private brief/history and progression display. Consume existing scenario data without changing it. |
| `ui/session.py` | Suggestion, peer-feedback form, turn-action composer and submission status. Return intents/values; do not change scoring, validation or joint-turn rules. |
| `ui/views.py` | Welcome, lobby and active layout composition. Keep three existing state branches rather than introducing a new navigation wizard. Expose container handles where existing controller-owned status updates require them. |
| `tests/test_ui_rendering.py` | Focused regression coverage for optional header markup, escaped content and rating output; Streamlit smoke coverage for state/layout and form interactions using isolated fixtures. |
| `assets/echorole_icon.png` | Preserve unchanged. |
| Backend/content modules | No planned changes to database schema, AI generation, retrieval, scenario content or message semantics. |

Layout direction for a later redesign: a compact session header with room/role/turn status; a clear story-and-coaching center; a distinct action/shared-chat area; quieter profile/room utilities. Retain all current controls and privacy boundaries. Centralize shared/private labels, card hierarchy and interaction states before adding immersive decoration. Use responsive widths and deliberate history disclosure, validated within Streamlit.

## 6. Short next-step implementation plan

1. Establish the actual Streamlit/runtime version and capture all three layouts plus key waiting/error states using an isolated database and stubbed AI responses. Record widget keys, submit callbacks and refresh behavior.
2. Extract theme/assets and safe HTML primitives while preserving the existing appearance. Reproduce and fix header leakage and the incomplete star meter as small, independently reviewable corrections.
3. Consolidate duplicated history/chat presentation, then extract forms and view composition one section at a time. Preserve keys, `clear_on_submit`, placeholders, URL state and rerun timing; do not cache user-specific content or database mutations.
4. Verify create/join/leave, scenario selection, role assignment, private-coach isolation, shared chat, peer feedback and two-participant turn progression. Check long content, keyboard focus and narrow/wide screens. Confirm no duplicate writes or lost drafts on refresh.
5. With structural parity established, implement the premium green-branded design within Streamlit, reviewing the three layouts before broad rollout. Keep workflow or game-mechanic changes outside this frontend refactor.
