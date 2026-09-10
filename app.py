from streamlit_autorefresh import st_autorefresh
import base64
from pathlib import Path
import streamlit as st
import html
import os
import re
import uuid
from datetime import datetime

from ai_engine import (
    build_turn_coach_prompt,
    generate_dynamic_ai_feedback,
    generate_next_situation_from_joint_actions,
    get_last_ai_debug_info,
    validate_turn_action,
)

from database import (
    get_room_event_version,
    bump_room_event_version,
    add_member,
    remove_member,
    add_message,
    get_messages_by_room,
    get_user_role,
    add_ai_message,
    get_ai_messages,
    get_recent_ai_messages_for_user,
    has_ai_prompt_for_turn,
    get_turn_history,
    save_pending_turn_action,
    get_pending_turn_actions_for_session_turn,
    get_pending_turn_action_for_user,
    mark_pending_turn_actions_consumed,
    reset_pending_turn_actions_to_pending,
    has_completed_turn,
    claim_pending_turn_actions_for_generation,
    complete_joint_turn,
    get_turn_suggestion,
    get_latest_story_state,
    get_recent_shared_chat_messages,
    get_recent_story_states,
    get_role_brief_history,
    get_peer_feedback_for_session,
    save_peer_feedback,
    get_total_received_peer_feedback_points,
)
from scenario_library import (
    get_scenario_by_id,
    get_scenario_categories,
    get_scenarios_by_category,
)

import application as services
from application import (
    get_room_by_code, get_members_by_room, can_user_join_room,
    get_user_profile, save_user_profile, get_session_by_room,
)

st.set_page_config(
    page_title="EchoRole",
    layout="wide"
)

services.initialize()

_pending_ai_coach_state_updates = {}
APP_RUNTIME_MARKER = "app_runtime_20260425_ai_reply_save_v3"


def short_debug_preview(text, limit=140):
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def normalize_app_text(value):
    if value is None:
        return ""

    if isinstance(value, bytes):
        normalized = value.decode("utf-8", errors="replace")
    else:
        normalized = str(value)

    normalized = normalized.replace("\x00", "")
    return normalized


def is_truthy_debug_flag(value):
    if value is None:
        return False

    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return False
        value = value[0]

    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def should_show_ai_coach_debug():
    return (
        is_truthy_debug_flag(os.getenv("ECHOROLE_SHOW_AI_DEBUG"))
        or is_truthy_debug_flag(st.query_params.get("debug"))
    )


def log_sync_event(event, **fields):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    field_parts = []
    for key, value in fields.items():
        if value is None:
            continue
        field_parts.append(f"{key}={value!r}")

    suffix = ""
    if field_parts:
        suffix = " " + " ".join(field_parts)

    print(
        f"[EchoRole][Sync][{timestamp}] event={event}{suffix}",
        flush=True
    )


def get_last_seen_room_event_version(room_id):
    room_versions = st.session_state.get("last_seen_room_event_versions") or {}
    return room_versions.get(str(room_id))


def set_last_seen_room_event_version(room_id, version):
    room_versions = dict(st.session_state.get("last_seen_room_event_versions") or {})
    room_versions[str(room_id)] = int(version or 0)
    st.session_state.last_seen_room_event_versions = room_versions


def clear_last_seen_room_event_version(room_id):
    room_versions = dict(st.session_state.get("last_seen_room_event_versions") or {})
    room_versions.pop(str(room_id), None)
    st.session_state.last_seen_room_event_versions = room_versions


def bump_room_sync_event(*, room_id, event_type, session_id=None):
    new_version = bump_room_event_version(
        room_id=room_id,
        event_type=event_type,
        session_id=session_id
    )
    log_sync_event(
        "sync_event_version_bumped",
        room_id=room_id,
        session_id=session_id,
        event_type=event_type,
        version=new_version
    )
    set_last_seen_room_event_version(room_id, new_version)
    return new_version


def check_room_sync_event_version(*, room_id, session_id=None, force=False):
    current_version = int(get_room_event_version(room_id))
    last_seen_version = get_last_seen_room_event_version(room_id)

    signature = (room_id, session_id, current_version, last_seen_version)
    previous_signature = st.session_state.get("sync_event_version_check_signature")
    if force or previous_signature != signature:
        log_sync_event(
            "sync_event_version_checked",
            room_id=room_id,
            session_id=session_id,
            current_version=current_version,
            last_seen_version=last_seen_version
        )
        st.session_state.sync_event_version_check_signature = signature

    if last_seen_version is None:
        set_last_seen_room_event_version(room_id, current_version)
        return False, current_version

    if current_version > int(last_seen_version):
        log_sync_event(
            "sync_event_change_detected",
            room_id=room_id,
            session_id=session_id,
            current_version=current_version,
            last_seen_version=last_seen_version
        )
        set_last_seen_room_event_version(room_id, current_version)
        return True, current_version

    if current_version < int(last_seen_version):
        set_last_seen_room_event_version(room_id, current_version)
        return False, current_version

    return False, current_version


def maybe_log_sync_polling_state(*, enabled, reason, interval_ms=None, room_id=None, session_id=None, force=False):
    signature = (enabled, reason, interval_ms, room_id, session_id)
    previous_signature = st.session_state.get("sync_polling_state_signature")
    if force or previous_signature != signature:
        event_name = "sync_polling_enabled" if enabled else "sync_polling_disabled"
        log_sync_event(
            event_name,
            room_id=room_id,
            session_id=session_id,
            reason=reason,
            interval_ms=interval_ms
        )
        st.session_state.sync_polling_state_signature = signature



def get_echorole_logo_data_uri():
    logo_path = Path(__file__).resolve().parent / "assets" / "echorole_icon.png"
    if not logo_path.exists():
        return ""

    try:
        encoded = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    except OSError:
        return ""

    return f"data:image/png;base64,{encoded}"
def inject_readability_styles():
    st.markdown(
        """
        <style>
        :root {
            --echorole-bg: #F7F3EC;
            --echorole-surface: rgba(255, 252, 247, 0.94);
            --echorole-accent: #7D9A86;
            --echorole-accent-strong: #668473;
            --echorole-accent-soft: #E8F0E8;
            --echorole-border: #D8E1D5;
            --echorole-border-strong: #C7D3C4;
            --echorole-text: #22313A;
            --echorole-text-soft: #5F6C71;
            --echorole-shadow: 0 16px 36px rgba(70, 86, 74, 0.08);
        }

        .block-container {
            max-width: 96vw !important;
            width: 96vw !important;
            padding-top: 1.15rem;
            padding-bottom: 2.35rem;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            margin: 0 auto;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(232, 240, 232, 0.9), transparent 30%),
                radial-gradient(circle at top right, rgba(246, 239, 223, 0.88), transparent 28%),
                linear-gradient(180deg, #FBF8F2 0%, var(--echorole-bg) 100%);
            color: var(--echorole-text);
            font-size: 1.08rem;
        }

        .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
            color: var(--echorole-text);
        }

        .stApp h1 { font-size: 2.55rem; line-height: 1.2; }
        .stApp h2 { font-size: 2rem; line-height: 1.25; }
        .stApp h3 { font-size: 1.65rem; line-height: 1.3; }
        .stApp h4 { font-size: 1.35rem; line-height: 1.35; }

        .stApp p,
        .stApp li,
        .stApp label,
        .stApp div[data-testid="stMarkdownContainer"] p,
        .stApp div[data-testid="stMarkdownContainer"] li,
        .stApp .stText,
        .stApp [data-testid="stCaptionContainer"] {
            font-size: 1.08rem;
            line-height: 1.62;
            color: var(--echorole-text);
        }

        .stApp [data-testid="stCaptionContainer"] {
            font-size: 1rem;
            color: var(--echorole-text-soft);
        }

        .stApp [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 24px;
            border: 1px solid var(--echorole-border);
            background: rgba(255, 252, 247, 0.94);
            box-shadow: var(--echorole-shadow);
            backdrop-filter: blur(8px);
        }

        .stApp [data-testid="stVerticalBlockBorderWrapper"] > div {
            padding-top: 0.35rem;
            padding-bottom: 0.18rem;
        }

        .stApp [data-testid="stExpander"] {
            border-radius: 20px;
            border: 1px solid var(--echorole-border) !important;
            background: rgba(255, 252, 247, 0.8);
        }

        .stApp [data-testid="stAlert"] {
            border-radius: 18px;
            border: 1px solid var(--echorole-border);
            box-shadow: 0 8px 22px rgba(70, 86, 74, 0.05);
        }

        .stApp textarea,
        .stApp input,
        .stApp [data-baseweb="select"] > div,
        .stApp [data-baseweb="base-input"] {
            border-radius: 18px !important;
            border-color: var(--echorole-border-strong) !important;
            background: rgba(255, 252, 247, 0.96) !important;
            color: var(--echorole-text) !important;
        }

        .stApp textarea,
        .stApp input,
        .stApp [data-baseweb="select"] div,
        .stApp [data-baseweb="select"] input {
            font-size: 1.05rem !important;
        }

        .stApp .stButton > button,
        .stApp .stDownloadButton > button,
        .stApp .stFormSubmitButton > button {
            font-size: 1.05rem;
            min-height: 2.9rem;
            padding: 0.62rem 1.2rem;
            border-radius: 999px;
            border: 1px solid var(--echorole-accent-strong);
            background: linear-gradient(180deg, #8DA99B 0%, #769281 100%);
            color: #FFFFFF;
            box-shadow: 0 12px 24px rgba(102, 132, 115, 0.24);
        }

        .stApp [data-testid="stVerticalBlock"] > div { gap: 0.45rem; }
        .stApp [data-testid="column"] > div { gap: 1.2rem; }

        .echorole-brand-card {
            margin: 0 0 1.8rem 0;
            padding: 1.4rem 1.5rem;
            border: 1px solid var(--echorole-border);
            border-radius: 28px;
            background: linear-gradient(135deg, rgba(255, 252, 247, 0.97) 0%, rgba(245, 248, 241, 0.95) 100%);
            box-shadow: 0 22px 40px rgba(88, 102, 92, 0.1);
        }

        .echorole-brand-grid {
            display: grid;
            grid-template-columns: minmax(88px, 112px) 1fr;
            gap: 1.1rem;
            align-items: center;
        }

        .echorole-brand-logo {
            width: 100%;
            max-width: 104px;
            aspect-ratio: 1 / 1;
            object-fit: cover;
            border-radius: 28px;
            border: 1px solid rgba(125, 154, 134, 0.22);
            box-shadow: 0 16px 30px rgba(125, 154, 134, 0.16);
            background: #FBF8F2;
        }

        .echorole-brand-badge {
            display: inline-flex;
            margin-bottom: 0.55rem;
            padding: 0.34rem 0.8rem;
            border-radius: 999px;
            border: 1px solid rgba(125, 154, 134, 0.28);
            background: var(--echorole-accent-soft);
            color: var(--echorole-accent-strong);
            font-size: 0.84rem;
            font-weight: 600;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }

        .echorole-brand-title {
            margin: 0;
            color: var(--echorole-text);
            font-size: 2.95rem;
            line-height: 1.02;
            letter-spacing: -0.04em;
            font-weight: 750;
        }

        .echorole-brand-subtitle {
            margin-top: 0.45rem;
            color: var(--echorole-text-soft);
            font-size: 1.08rem;
            line-height: 1.65;
            max-width: 52rem;
        }

        .echorole-brand-accent {
            width: 144px;
            height: 5px;
            margin-top: 0.95rem;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--echorole-accent) 0%, #D7E6D6 100%);
        }

        .echorole-page-intro {
            margin-top: 0.9rem;
            padding: 0.95rem 1.05rem;
            border-radius: 22px;
            border: 1px dashed rgba(125, 154, 134, 0.26);
            background: rgba(248, 244, 235, 0.78);
            color: var(--echorole-text-soft);
            font-size: 1rem;
        }

        .echorole-section-kicker {
            margin-bottom: 0.45rem;
            color: var(--echorole-accent-strong);
            font-size: 0.88rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        .echorole-room-code-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            margin-top: 0.75rem;
            padding: 0.48rem 0.9rem;
            border-radius: 999px;
            border: 1px solid rgba(125, 154, 134, 0.28);
            background: rgba(255, 252, 247, 0.88);
            color: var(--echorole-text);
            font-size: 0.95rem;
            font-weight: 600;
        }

        .echorole-room-code-pill strong {
            color: var(--echorole-accent-strong);
        }

        .echorole-situation-card {
            margin-bottom: 1.2rem;
            padding: 1.55rem 1.65rem;
            border: 1px solid rgba(125, 154, 134, 0.2);
            border-left: 6px solid var(--echorole-accent);
            border-radius: 24px;
            background: linear-gradient(135deg, #EFF5EC 0%, #FFFDF8 100%);
            box-shadow: 0 18px 34px rgba(102, 132, 115, 0.12);
        }

        .echorole-situation-title {
            margin-bottom: 0.48rem;
            color: var(--echorole-accent-strong);
            font-size: 0.98rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        .echorole-situation-body {
            color: var(--echorole-text);
            font-size: 1.17rem;
            line-height: 1.75;
        }

        .echorole-meta-id {
            margin-top: 0.35rem;
            color: var(--echorole-text-soft);
            font-size: 0.95rem;
            overflow-wrap: anywhere;
        }

        .echorole-rating-question {
            margin-bottom: 0.7rem;
            color: var(--echorole-text);
            line-height: 1.6;
        }

        .echorole-star-meter-back { color: #D9D8CF; }
        .echorole-rating-meta { color: var(--echorole-text-soft); font-size: 0.98rem; margin-top: 0.1rem; }
        </style>
        """,
        unsafe_allow_html=True
    )

def inject_active_session_dashboard_styles():
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 96vw !important;
            width: 96vw !important;
            padding-bottom: 2.65rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def get_role_display_name(role_name):
    if role_name == "role_a":
        return "Role A"
    if role_name == "role_b":
        return "Role B"
    if role_name == "joint":
        return "Joint Turn"
    return "Unassigned"


def render_app_header(
    *,
    dashboard=False,
    badge=None,
    subtitle=None,
    supporting_text=None,
    room_code=None
):
    logo_data_uri = get_echorole_logo_data_uri()
    resolved_badge = normalize_app_text(badge or ("Active Session" if dashboard else "Welcome"))
    resolved_subtitle = normalize_app_text(
        subtitle or "Role-play decision training for difficult conversations"
    )
    resolved_supporting_text = normalize_app_text(supporting_text)
    resolved_room_code = normalize_app_text(room_code)

    logo_markup = ""
    if logo_data_uri:
        logo_markup = (
            f'<img class="echorole-brand-logo" src="{logo_data_uri}" alt="EchoRole logo" />'
        )

    room_code_markup = ""
    if resolved_room_code:
        room_code_markup = (
            f'<div class="echorole-room-code-pill"><span>Room code</span> '
            f'<strong>{html.escape(resolved_room_code)}</strong></div>'
        )

    supporting_markup = ""
    if resolved_supporting_text:
        supporting_markup = (
            f'<div class="echorole-page-intro">{html.escape(resolved_supporting_text)}</div>'
        )

    st.markdown(
        f"""
        <div class="echorole-brand-card">
            <div class="echorole-brand-grid">
                <div>{logo_markup}</div>
                <div>
                    <div class="echorole-brand-badge">{html.escape(resolved_badge)}</div>
                    <div class="echorole-brand-title">EchoRole</div>
                    <div class="echorole-brand-subtitle">{html.escape(resolved_subtitle)}</div>
                    <div class="echorole-brand-accent"></div>
                    {room_code_markup}
                </div>
            </div>
            {supporting_markup}
        </div>
        """,
        unsafe_allow_html=True
    )

def render_text_card(title, body, *, caption=None, empty_message="Not available yet."):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        if caption:
            st.caption(caption)
        value = normalize_app_text(body)
        if value.strip():
            st.write(value)
        else:
            st.caption(empty_message)


def render_profile_card(user_profile, user_role, total_points=0):
    display_name = normalize_app_text(
        (user_profile or {}).get("display_name")
        or st.session_state.get("username")
        or ""
    )
    mbti = normalize_app_text((user_profile or {}).get("mbti"))
    priorities = normalize_app_text((user_profile or {}).get("priorities"))

    with st.container(border=True):
        st.markdown('<div class="echorole-section-kicker">Your profile</div>', unsafe_allow_html=True)
        st.markdown("**Profile**")
        st.write(f"**Display name:** {display_name or 'Not set'}")
        st.write(f"**Role:** {get_role_display_name(user_role)}")
        st.write(f"**Peer score:** {int(total_points or 0)} points")
        if mbti:
            st.write(f"**MBTI:** {mbti}")
        if priorities:
            st.write(f"**Profile context:** {priorities}")
        if not mbti and not priorities:
            st.caption("No additional profile context yet.")

def render_room_info_card(invite_code, username, user_id):
    normalized_code = normalize_app_text(invite_code) or "(missing)"
    with st.container(border=True):
        st.markdown('<div class="echorole-section-kicker">Room lobby</div>', unsafe_allow_html=True)
        st.markdown("**Room Information**")
        st.markdown(
            f'<div class="echorole-room-code-pill"><span>Room code</span> <strong>{html.escape(normalized_code)}</strong></div>',
            unsafe_allow_html=True
        )
        st.write(f"**Signed in as:** {normalize_app_text(username) or '(missing)'}")
        normalized_user_id = normalize_app_text(user_id) or "(missing)"
        st.markdown(
            f'<div class="echorole-meta-id">User ID: {html.escape(normalized_user_id)}</div>',
            unsafe_allow_html=True
        )

def render_members_card(members):
    with st.container(border=True):
        st.markdown('<div class="echorole-section-kicker">Participants</div>', unsafe_allow_html=True)
        st.markdown("**Members in this Room**")
        if not members:
            st.caption("No members in this room yet.")
            return

        for index, member in enumerate(members, start=1):
            user_id = normalize_app_text(member[0] if len(member) > 0 else "")
            nickname = normalize_app_text(member[1] if len(member) > 1 else "")
            label = nickname or user_id or "(unknown member)"
            st.write(f"**Member {index}:** {label}")

def render_profile_editor(user_profile):
    with st.expander("Edit Profile"):
        with st.form("profile_form"):
            profile_display_name = st.text_input(
                "Display name",
                value=user_profile.get("display_name") or st.session_state.username
            )
            profile_mbti = st.text_input(
                "MBTI",
                value=user_profile.get("mbti", "")
            )
            profile_priorities = st.text_area(
                "Communication / value priorities",
                value=user_profile.get("priorities", "")
            )
            profile_submitted = st.form_submit_button("Save Profile")

            if profile_submitted:
                profile_display_name_value = (profile_display_name or "").strip()
                profile_mbti_value = (profile_mbti or "").strip()
                profile_priorities_value = (profile_priorities or "").strip()

                if profile_display_name_value == "":
                    st.error("Display name cannot be empty.")
                else:
                    st.session_state.username = profile_display_name_value
                    save_user_profile(
                        st.session_state.user_id,
                        display_name=profile_display_name_value,
                        mbti=profile_mbti_value,
                        priorities=profile_priorities_value
                    )
                    add_member(
                        st.session_state.user_id,
                        st.session_state.room_id,
                        st.session_state.username
                    )
                    if st.session_state.room_id is not None:
                        bump_room_sync_event(
                            room_id=st.session_state.room_id,
                            event_type="profile_updated"
                        )
                    save_user_to_url()
                    st.success("Profile saved.")
                    st.rerun()


def render_current_turn_card(current_turn, user_role):
    with st.container(border=True):
        st.markdown("**Current Turn**")
        st.write(f"**Turn:** {current_turn}")
        st.write(f"**Your role:** {get_role_display_name(user_role)}")


def render_recent_progression_history_card(recent_turn_history):
    with st.container(border=True):
        st.markdown("**Recent Progression History**")
        if not recent_turn_history:
            st.caption("No previous actions yet.")
            return

        for turn in recent_turn_history:
            with st.container(border=True):
                st.write(
                    f"**Turn {turn.get('turn_index', '?')} 路 {get_role_display_name(turn.get('role_name'))}**"
                )
                st.write(
                    f"**Action:** {normalize_app_text(turn.get('submitted_action')) or '(empty)'}"
                )
                st.write(
                    f"**Result:** {normalize_app_text(turn.get('resulting_situation')) or '(empty)'}"
                )


def render_recent_progression_history_card(recent_turn_history):
    with st.container(border=True):
        st.markdown("**Recent Progression History**")
        if not recent_turn_history:
            st.caption("No previous actions yet.")
            return

        for turn in recent_turn_history:
            with st.container(border=True):
                turn_index = turn.get("turn_index", "?")
                role_label = get_role_display_name(turn.get("role_name"))
                st.write(f"**Turn {turn_index} - {role_label}**")
                submitted_action = normalize_app_text(turn.get("submitted_action"))
                if turn.get("role_name") == "joint":
                    role_a_match = re.search(
                        r"Role A action:\s*(.*?)\s*Role B action:\s*(.*)",
                        submitted_action,
                        re.DOTALL
                    )
                    if role_a_match:
                        st.write(f"**Role A action:** {role_a_match.group(1).strip() or '(empty)'}")
                        st.write(f"**Role B action:** {role_a_match.group(2).strip() or '(empty)'}")
                    else:
                        st.write(f"**Action:** {submitted_action or '(empty)'}")
                else:
                    st.write(f"**Action:** {submitted_action or '(empty)'}")
                st.write(
                    f"**Result:** {normalize_app_text(turn.get('resulting_situation')) or '(empty)'}"
                )


def render_ai_suggestion_card(suggestion_text):
    render_text_card(
        "AI Suggestion for Your Next Move",
        suggestion_text,
        caption="Private guidance for your current role.",
        empty_message="No private suggestion yet for this turn."
    )


def render_role_brief_history_card(role_name, role_history):
    with st.container(border=True):
        st.markdown("**Private Role Brief**")
        st.caption("Private to your role. Earlier briefs remain visible so you can track how your role evolves.")
        if not role_history:
            st.caption("No private role brief history yet.")
            return

        role_label = get_role_display_name(role_name)
        for entry in role_history:
            turn_number = entry.get("turn_number", "?")
            brief_text = normalize_app_text(entry.get("brief_text"))
            with st.container(border=True):
                st.write(f"**{role_label} Brief — Turn {turn_number}**")
                st.write(brief_text or "Not available yet.")


def render_coach_reflection_prompt_card():
    with st.container(border=True):
        st.markdown("**Coach Reflection Prompt**")
        st.write(
            "Reflect on what matters most to you right now, what risk you see, and what move you are considering next."
        )


def render_current_situation_feature_card(current_situation):
    body = normalize_app_text(current_situation).strip()
    if body == "":
        body = "Current situation is not available yet."

    st.markdown(
        f"""
        <div class="echorole-situation-card">
            <div class="echorole-situation-title">Current Situation</div>
            <div class="echorole-situation-body">{html.escape(body).replace(chr(10), "<br>")}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_scenario_overview_cards(
    scenario_title,
    scenario_context,
    conflict,
    current_turn,
    current_situation=None,
    *,
    show_current_situation=True
):
    with st.container(border=True):
        st.markdown('<div class="echorole-section-kicker">Scenario setup</div>', unsafe_allow_html=True)
        st.markdown("**Scenario Overview**")
        st.write(f"**Title:** {normalize_app_text(scenario_title) or 'Not available yet.'}")
        st.write(f"**Current Turn:** {current_turn}")
        st.write(f"**Context:** {normalize_app_text(scenario_context) or 'Not available yet.'}")
        st.write(f"**Conflict:** {normalize_app_text(conflict) or 'Not available yet.'}")
        if show_current_situation:
            st.write(
                f"**Current Situation:** {normalize_app_text(current_situation) or 'Not available yet.'}"
            )

def get_other_room_member(members, current_user_id):
    for member in members or []:
        member_user_id = member[0] if len(member) > 0 else ""
        if member_user_id and member_user_id != current_user_id:
            return member
    return None


def render_star_rating_preview(star_rating):
    numeric_rating = float(star_rating or 0)
    if numeric_rating <= 0:
        normalized_rating = 0.0
    else:
        normalized_rating = max(0.5, min(5.0, round(numeric_rating * 2) / 2))

    fill_percent = normalized_rating / 5.0 * 100.0
    points = int(round(normalized_rating * 10))
    star_markup = "&#9733;&#9733;&#9733;&#9733;&#9733;"
    meta_text = (
        "Choose a rating from 0.5 to 5.0 stars."
        if normalized_rating == 0
        else f"{normalized_rating:.1f} stars - {points} points"
    )

    st.markdown(
        f"""
        <div class="echorole-star-meter" aria-hidden="true">
            <div class="echorole-star-meter-back">{star_markup}</div>
            <div class="echorole-star-meter-front" style="width: {fill_percent:.1f}%;">{star_markup}</div>
        </div>
        <div class="echorole-rating-meta">{meta_text}</div>
        """
        , unsafe_allow_html=True
    )


def render_peer_feedback_card(
    *,
    room_id,
    session_id,
    current_turn,
    current_user_id,
    other_member
):
    if current_turn < 3:
        return

    with st.container(border=True):
        st.markdown("**Peer Feedback**")

        if other_member is None:
            st.caption("Peer feedback becomes available once another participant is present.")
            return

        rated_user_id = other_member[0] if len(other_member) > 0 else ""
        rated_display_name = normalize_app_text(other_member[1] if len(other_member) > 1 else "") or rated_user_id
        existing_feedback = get_peer_feedback_for_session(
            session_id=session_id,
            rater_user_id=current_user_id,
            rated_user_id=rated_user_id
        )

        st.markdown(
            """
            <div class="echorole-rating-question">
                How well did your partner handle this conversation?
            </div>
            """
            , unsafe_allow_html=True
        )
        st.caption(f"Your feedback for: {rated_display_name}")

        if existing_feedback is not None:
            render_star_rating_preview(existing_feedback.get("star_rating", 5.0))
            st.success("Feedback submitted.")
            saved_comment = normalize_app_text(existing_feedback.get("comment"))
            if saved_comment:
                st.write("**Your private comment:**")
                st.write(saved_comment)
            return

        rating_key = f"peer_feedback_rating_{session_id}_{current_user_id}_{rated_user_id}"
        comment_key = f"peer_feedback_comment_{session_id}_{current_user_id}_{rated_user_id}"
        submit_key = f"peer_feedback_submit_{session_id}_{current_user_id}_{rated_user_id}"

        selected_rating = st.select_slider(
            "Rating",
            options=[0.0] + [value / 2 for value in range(1, 11)],
            value=0.0,
            key=rating_key,
            format_func=lambda value: "Select rating" if value == 0 else f"{value:.1f} stars"
        )
        render_star_rating_preview(selected_rating)

        comment_value = st.text_area(
            "Private comment",
            key=comment_key,
            placeholder="Leave a private comment for your partner/opponent..."
        )

        if st.button("Submit Feedback", key=submit_key):
            if float(selected_rating or 0) <= 0:
                st.error("Please choose a rating before submitting.")
                return

            saved_feedback = save_peer_feedback(
                room_id=room_id,
                session_id=session_id,
                rater_user_id=current_user_id,
                rated_user_id=rated_user_id,
                star_rating=selected_rating,
                comment=comment_value
            )
            if saved_feedback is None:
                st.error("Feedback could not be saved.")
            else:
                bump_room_sync_event(
                    room_id=room_id,
                    session_id=session_id,
                    event_type="peer_feedback_submitted"
                )
                st.success("Feedback submitted.")
                st.rerun()


def render_ai_coach_context_cards(
    *,
    private_role_brief,
    recent_turn_history
):
    render_text_card("Private Role Brief", private_role_brief)
    render_recent_progression_history_card(recent_turn_history)
    render_coach_reflection_prompt_card()


def is_ai_coach_context_prompt_message(content, hidden_ai_prompt_content=None):
    normalized_content = normalize_app_text(content).strip()
    normalized_hidden_prompt = normalize_app_text(hidden_ai_prompt_content).strip()

    if normalized_hidden_prompt and normalized_content == normalized_hidden_prompt:
        return True

    return (
        normalized_content.startswith("Turn ")
        and "Current situation:" in normalized_content
        and "Your private role brief:" in normalized_content
        and "Reflect on what matters most to you right now" in normalized_content
    )


def is_turn_action_validation_feedback_message(content):
    normalized_content = normalize_app_text(content).strip()
    if normalized_content == "":
        return False

    english_markers = (
        "I cannot advance the story from this action yet:",
        "Please describe one concrete action you take next, such as what you say, ask, offer, accept, refuse, or suggest.",
        "Your action needs to be more concrete before the scenario can advance.",
    )
    chinese_markers = (
        "这个行动目前还不能推进剧情：",
        "请描述你接下来会采取的一个具体行动，比如你会说什么、询问什么、提供什么、接受什么、拒绝什么，或建议什么。",
        "你的行动需要更具体一些，剧情才能继续推进。",
    )

    return normalized_content.startswith(english_markers + chinese_markers)


def maybe_log_ai_coach_history_filter_event(
    *,
    session_id=None,
    user_id=None,
    turn_index=None,
    filtered_validation_count=0,
    filtered_action_count=0,
    force=False
):
    if filtered_validation_count <= 0 and filtered_action_count <= 0:
        return

    signature = (
        session_id,
        user_id,
        turn_index,
        filtered_validation_count,
        filtered_action_count,
    )
    previous_signature = st.session_state.get("ai_coach_history_filter_signature")
    if force or previous_signature != signature:
        log_ai_submit_event(
            "ai_coach_history_filtered_validation_messages",
            session_id=session_id,
            user_id=user_id,
            turn_index=turn_index,
            filtered_validation_count=filtered_validation_count,
            filtered_action_count=filtered_action_count,
        )
        st.session_state.ai_coach_history_filter_signature = signature


def render_ai_coach_messages(
    message_container,
    ai_messages,
    submit_trace_id=None,
    hidden_ai_prompt_content=None
):
    should_log_render_details = (
        submit_trace_id is not None
        or should_show_ai_coach_debug()
    )

    def log_render_event(event, **fields):
        if should_log_render_details:
            log_ai_submit_event(
                event,
                submit_trace_id=submit_trace_id,
                **fields
            )

    log_render_event(
        "render_ai_coach_messages_entered",
        message_count=len(ai_messages)
    )
    log_render_event(
        "render_ai_coach_messages_container_type",
        container_type=type(message_container).__name__
    )

    try:
        skipped_prompt = False
        visible_messages = []
        filtered_validation_count = 0
        filtered_action_count = 0
        for index, msg in enumerate(ai_messages):
            sender = msg[0]
            content = msg[1]
            if (
                not skipped_prompt
                and sender == "ai"
                and is_ai_coach_context_prompt_message(
                    content,
                    hidden_ai_prompt_content=hidden_ai_prompt_content
                )
            ):
                skipped_prompt = True
                log_render_event(
                    "render_ai_coach_messages_skipped_context_prompt",
                    index=index
                )
                continue

            if sender == "action":
                filtered_action_count += 1
                continue

            if sender == "ai" and is_turn_action_validation_feedback_message(content):
                filtered_validation_count += 1
                continue

            visible_messages.append(msg)

        maybe_log_ai_coach_history_filter_event(
            filtered_validation_count=filtered_validation_count,
            filtered_action_count=filtered_action_count,
            force=should_show_ai_coach_debug()
        )

        log_render_event("render_ai_coach_messages_before_container_context")
        with message_container.container():
            if len(visible_messages) == 0:
                log_render_event(
                    "render_ai_coach_messages_before_loop",
                    message_count=0
                )
                st.caption("No AI chat replies yet. Start by sharing your reflection below.")
                log_render_event(
                    "render_ai_coach_messages_after_loop",
                    rendered_message_count=0
                )
            else:
                log_render_event(
                    "render_ai_coach_messages_before_loop",
                    message_count=len(visible_messages)
                )
                for index, msg in enumerate(visible_messages):
                    sender = msg[0]
                    content = msg[1]
                    created_at = msg[2]
                    log_render_event(
                        "render_ai_coach_messages_each_message",
                        index=index,
                        sender=sender,
                        content_preview=short_debug_preview(content, 80)
                    )

                    if sender == "ai":
                        st.info(f"AI: {content}")
                    elif sender == "action":
                        st.caption(f"Your submitted action: {content}")
                    else:
                        st.write(f"**You:** {content}")

                log_render_event(
                    "render_ai_coach_messages_after_loop",
                    rendered_message_count=len(visible_messages)
                )
        log_render_event("render_ai_coach_messages_after_container_context")
    except Exception as exc:
        log_render_event(
            "render_ai_coach_messages_exception",
            exception_type=type(exc).__name__,
            exception_message=str(exc)
        )
        raise

    log_render_event("render_ai_coach_messages_exited")


def get_visible_ai_coach_history_entries(
    ai_messages,
    *,
    hidden_ai_prompt_content=None,
    limit=8,
    session_id=None,
    user_id=None,
    turn_index=None
):
    visible_messages = []
    filtered_validation_count = 0
    filtered_action_count = 0

    for msg in ai_messages:
        if len(msg) < 4:
            continue

        turn_index = msg[0]
        sender = msg[2]
        content = msg[3]
        created_at = msg[4]

        if (
            sender == "ai"
            and is_ai_coach_context_prompt_message(
                content,
                hidden_ai_prompt_content=hidden_ai_prompt_content
            )
        ):
            continue

        if sender == "action":
            filtered_action_count += 1
            continue

        if sender == "ai" and is_turn_action_validation_feedback_message(content):
            filtered_validation_count += 1
            continue

        visible_messages.append(
            {
                "turn_index": turn_index,
                "sender": sender,
                "content": normalize_app_text(content),
                "created_at": created_at,
            }
        )

    maybe_log_ai_coach_history_filter_event(
        session_id=session_id,
        user_id=user_id,
        turn_index=turn_index,
        filtered_validation_count=filtered_validation_count,
        filtered_action_count=filtered_action_count,
    )

    if limit <= 0:
        return visible_messages

    return visible_messages[-limit:]


def get_visible_ai_coach_debug(session_id, user_id, current_turn):
    debug_snapshot = st.session_state.get("last_ai_coach_debug")
    if not debug_snapshot:
        return None

    if debug_snapshot.get("session_id") != session_id:
        return None

    if debug_snapshot.get("user_id") != user_id:
        return None

    visible_snapshot = dict(debug_snapshot)
    visible_snapshot["is_current_turn_snapshot"] = (
        visible_snapshot.get("turn_index") == current_turn
    )
    return visible_snapshot


def update_ai_coach_debug_snapshot(**kwargs):
    current_snapshot = st.session_state.get("last_ai_coach_debug") or {}
    submit_trace_id = (
        kwargs.get("submit_trace_id")
        or current_snapshot.get("submit_trace_id")
    )
    log_ai_submit_event(
        "update_debug_snapshot_start",
        submit_trace_id=submit_trace_id,
        incoming_keys=sorted(kwargs.keys())
    )
    updated_snapshot = {
        **current_snapshot,
        **kwargs,
    }
    try:
        st.session_state.last_ai_coach_debug = updated_snapshot
        log_ai_submit_event(
            "update_debug_snapshot_assigned",
            submit_trace_id=submit_trace_id,
            pipeline_stage=updated_snapshot.get("pipeline_stage"),
            provider=updated_snapshot.get("provider"),
            provider_stage=updated_snapshot.get("provider_stage")
        )
    except BaseException as exc:
        log_ai_submit_event(
            "update_debug_snapshot_exception",
            submit_trace_id=submit_trace_id,
            exception_type=type(exc).__name__,
            pipeline_error=str(exc)
        )
        raise
    return updated_snapshot


def log_ai_submit_event(event, submit_trace_id=None, **fields):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trace_label = submit_trace_id or "-"
    field_parts = []
    for key, value in fields.items():
        if value is None:
            continue
        field_parts.append(f"{key}={value!r}")

    suffix = ""
    if field_parts:
        suffix = " " + " ".join(field_parts)

    print(
        f"[EchoRole][AppSubmit][{timestamp}] trace={trace_label} event={event}{suffix}",
        flush=True
    )


def log_turn_action_event(event, submit_trace_id=None, **fields):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trace_label = submit_trace_id or "-"
    field_parts = []
    for key, value in fields.items():
        if value is None:
            continue
        field_parts.append(f"{key}={value!r}")

    suffix = ""
    if field_parts:
        suffix = " " + " ".join(field_parts)

    print(
        f"[EchoRole][TurnAction][{timestamp}] trace={trace_label} event={event}{suffix}",
        flush=True
    )


def maybe_log_pending_turn_ui_status(
    *,
    session_id,
    turn_index,
    current_user_pending_action,
    other_pending_action,
    pending_count,
    force=False
):
    current_status = None
    if current_user_pending_action is not None:
        current_status = current_user_pending_action.get("status")

    other_status = None
    if other_pending_action is not None:
        other_status = other_pending_action.get("status")

    signature = (
        session_id,
        turn_index,
        pending_count,
        current_status,
        other_status,
        current_user_pending_action is not None,
        other_pending_action is not None,
    )
    previous_signature = st.session_state.get("pending_turn_ui_log_signature")

    if force or previous_signature != signature:
        log_turn_action_event(
            "pending_turn_actions_loaded_for_ui",
            session_id=session_id,
            turn_index=turn_index,
            current_user_has_pending=current_user_pending_action is not None,
            other_participant_has_pending=other_pending_action is not None,
            current_user_pending_status=current_status,
            other_pending_status=other_status,
            pending_count=pending_count
        )
        st.session_state.pending_turn_ui_log_signature = signature


def maybe_log_pending_turn_wait_event(event_name, signature, **fields):
    state_key = f"{event_name}_signature"
    previous_signature = st.session_state.get(state_key)
    force = fields.pop("force", False)
    if force or previous_signature != signature:
        log_turn_action_event(event_name, **fields)
        st.session_state[state_key] = signature


def load_pending_turn_state(*, session_id, turn_index, current_user_id):
    active_pending_actions = get_pending_turn_actions_for_session_turn(session_id, turn_index)
    current_user_pending_action = get_pending_turn_action_for_user(
        session_id,
        turn_index,
        current_user_id
    )
    other_pending_action = next(
        (
            action for action in active_pending_actions
            if action["user_id"] != current_user_id
        ),
        None
    )
    other_participant_submitted = other_pending_action is not None
    actions_by_role = {
        action.get("role_name"): action
        for action in active_pending_actions
        if action.get("role_name")
    }
    return {
        "active_pending_actions": active_pending_actions,
        "current_user_pending_action": current_user_pending_action,
        "other_pending_action": other_pending_action,
        "other_participant_submitted": other_participant_submitted,
        "actions_by_role": actions_by_role,
    }


def process_claimed_joint_turn(
    *,
    session_id,
    current_turn,
    submit_room_id,
    evolved_current_session,
    recent_turn_history,
    actions_by_role,
    submit_trace_id,
    trigger_source="submit"
):
    role_a_action = normalize_app_text(
        (actions_by_role.get("role_a") or {}).get("action_text")
    )
    role_b_action = normalize_app_text(
        (actions_by_role.get("role_b") or {}).get("action_text")
    )
    if trigger_source == "render":
        log_turn_action_event(
            "joint_turn_generation_started_from_render",
            submit_trace_id=submit_trace_id,
            session_id=session_id,
            turn_index=current_turn
        )
    generation_status = st.empty()
    generation_status.caption("Generating next situation from both actions...")
    log_turn_action_event(
        "joint_turn_generation_started",
        submit_trace_id=submit_trace_id,
        session_id=session_id,
        turn_index=current_turn
    )
    recent_shared_chat = get_recent_shared_chat_messages(
        session_id=session_id,
        limit=6
    )
    log_turn_action_event(
        "story_progression_generation_started",
        submit_trace_id=submit_trace_id,
        session_id=session_id,
        previous_turn_index=current_turn,
        new_turn_index=current_turn + 1,
        role_a_action_preview=short_debug_preview(role_a_action),
        role_b_action_preview=short_debug_preview(role_b_action),
        shared_chat_message_count=len(recent_shared_chat),
        progression_history_count=len(recent_turn_history)
    )
    joint_turn_result = generate_next_situation_from_joint_actions(
        current_session=evolved_current_session,
        role_a_action=role_a_action,
        role_b_action=role_b_action,
        recent_turn_history=recent_turn_history,
        recent_shared_chat=recent_shared_chat,
        debug_trace_id=submit_trace_id
    )
    shared_situation = normalize_app_text(
        (joint_turn_result or {}).get("shared_situation")
        or (joint_turn_result or {}).get("next_situation")
    )
    role_a_perspective = normalize_app_text(
        (joint_turn_result or {}).get("role_a_perspective")
    )
    role_b_perspective = normalize_app_text(
        (joint_turn_result or {}).get("role_b_perspective")
    )
    next_decision_point = normalize_app_text(
        (joint_turn_result or {}).get("next_decision_point")
    )
    updated_role_a_brief = normalize_app_text(
        (joint_turn_result or {}).get("updated_role_a_brief")
    )
    updated_role_b_brief = normalize_app_text(
        (joint_turn_result or {}).get("updated_role_b_brief")
    )
    role_a_suggestion = normalize_app_text(
        (joint_turn_result or {}).get("role_a_suggestion")
    )
    role_b_suggestion = normalize_app_text(
        (joint_turn_result or {}).get("role_b_suggestion")
    )
    log_turn_action_event(
        "evolved_role_brief_generated",
        submit_trace_id=submit_trace_id,
        session_id=session_id,
        new_turn_index=current_turn + 1,
        role_a_brief_preview=short_debug_preview(updated_role_a_brief),
        role_b_brief_preview=short_debug_preview(updated_role_b_brief)
    )
    log_turn_action_event(
        "joint_turn_generation_completed",
        submit_trace_id=submit_trace_id,
        next_situation_length=len((shared_situation or "").strip()),
        next_situation_preview=short_debug_preview(shared_situation)
    )
    log_turn_action_event(
        "story_progression_generation_completed",
        submit_trace_id=submit_trace_id,
        session_id=session_id,
        previous_turn_index=current_turn,
        new_turn_index=current_turn + 1,
        role_a_action_preview=short_debug_preview(role_a_action),
        role_b_action_preview=short_debug_preview(role_b_action),
        shared_chat_message_count=len(recent_shared_chat),
        progression_history_count=len(recent_turn_history),
        shared_situation_preview=short_debug_preview(shared_situation),
        next_decision_point_preview=short_debug_preview(next_decision_point)
    )

    if (shared_situation or "").strip() == "":
        reset_pending_turn_actions_to_pending(session_id, current_turn)
        st.error("The next situation could not be generated. Please try again.")
        return False

    action_summary = (
        f"Role A action: {role_a_action}\n\n"
        f"Role B action: {role_b_action}"
    )
    log_turn_action_event(
        "joint_turn_persistence_started",
        submit_trace_id=submit_trace_id,
        session_id=session_id,
        turn_index=current_turn
    )
    persisted = complete_joint_turn(
        session_id=session_id,
        expected_turn=current_turn,
        submitted_action_summary=action_summary,
        resulting_situation=shared_situation,
        role_a_perspective=role_a_perspective,
        role_b_perspective=role_b_perspective,
        next_decision_point=next_decision_point,
        role_a_brief=updated_role_a_brief,
        role_b_brief=updated_role_b_brief,
        role_a_suggestion=role_a_suggestion,
        role_b_suggestion=role_b_suggestion
    )

    if persisted:
        log_turn_action_event(
            "evolved_role_brief_saved",
            submit_trace_id=submit_trace_id,
            session_id=session_id,
            new_turn_index=current_turn + 1,
            role_a_brief_preview=short_debug_preview(updated_role_a_brief),
            role_b_brief_preview=short_debug_preview(updated_role_b_brief)
        )
        if updated_role_a_brief:
            log_turn_action_event(
                "role_brief_turn_saved",
                submit_trace_id=submit_trace_id,
                session_id=session_id,
                role_name="role_a",
                brief_turn_number=current_turn,
                brief_preview=short_debug_preview(updated_role_a_brief)
            )
        if updated_role_b_brief:
            log_turn_action_event(
                "role_brief_turn_saved",
                submit_trace_id=submit_trace_id,
                session_id=session_id,
                role_name="role_b",
                brief_turn_number=current_turn,
                brief_preview=short_debug_preview(updated_role_b_brief)
            )
        bump_room_sync_event(
            room_id=submit_room_id,
            session_id=session_id,
            event_type="joint_turn_progressed"
        )
        log_turn_action_event(
            "joint_turn_suggestions_saved",
            submit_trace_id=submit_trace_id,
            next_turn_index=current_turn + 1,
            role_a_suggestion_preview=short_debug_preview(role_a_suggestion),
            role_b_suggestion_preview=short_debug_preview(role_b_suggestion)
        )
        try:
            for pending_action in actions_by_role.values():
                add_ai_message(
                    session_id=session_id,
                    turn_index=current_turn,
                    user_id=pending_action["user_id"],
                    role_name=pending_action["role_name"],
                    sender="action",
                    content=pending_action["action_text"]
                )
        except Exception as exc:
            log_turn_action_event(
                "joint_turn_action_message_save_failed",
                submit_trace_id=submit_trace_id,
                exception_type=type(exc).__name__,
                exception_message=str(exc)
            )

        log_turn_action_event(
            "pending_turn_actions_consumed",
            submit_trace_id=submit_trace_id,
            session_id=session_id,
            turn_index=current_turn
        )
        reloaded_session = get_session_by_room(submit_room_id)
        reloaded_turn = None
        reloaded_situation_preview = ""
        if reloaded_session is not None:
            reloaded_turn = reloaded_session.get("current_turn")
            reloaded_situation_preview = short_debug_preview(
                reloaded_session.get("current_situation", "")
            )
        log_turn_action_event(
            "joint_turn_persistence_completed",
            submit_trace_id=submit_trace_id,
            reloaded_current_turn=reloaded_turn,
            reloaded_current_situation_preview=reloaded_situation_preview
        )
        log_turn_action_event(
            "story_progression_saved",
            submit_trace_id=submit_trace_id,
            session_id=session_id,
            previous_turn_index=current_turn,
            new_turn_index=current_turn + 1,
            role_a_action_preview=short_debug_preview(role_a_action),
            role_b_action_preview=short_debug_preview(role_b_action),
            shared_chat_message_count=len(recent_shared_chat),
            progression_history_count=len(recent_turn_history),
            shared_situation_preview=short_debug_preview(shared_situation),
            next_decision_point_preview=short_debug_preview(next_decision_point)
        )
        st.success("Both actions were applied. The story advanced to the next turn.")
        st.rerun()

    if has_completed_turn(session_id, current_turn):
        mark_pending_turn_actions_consumed(session_id, current_turn)
        log_turn_action_event(
            "joint_turn_already_completed_skip_generation",
            submit_trace_id=submit_trace_id,
            session_id=session_id,
            turn_index=current_turn
        )
        st.info("This turn was already completed elsewhere. Reloading the latest scenario state.")
        st.rerun()

    reset_pending_turn_actions_to_pending(session_id, current_turn)
    st.error("The joint turn could not be saved. Please try again.")
    return False


def set_turn_action_validation_feedback(*, session_id, turn_index, user_id, message):
    normalized_message = normalize_app_text(message).strip()
    if normalized_message == "":
        st.session_state.pop("turn_action_validation_feedback", None)
        return

    st.session_state.turn_action_validation_feedback = {
        "session_id": session_id,
        "turn_index": turn_index,
        "user_id": user_id,
        "message": normalized_message,
    }


def clear_turn_action_validation_feedback(*, session_id=None, turn_index=None, user_id=None):
    feedback_state = st.session_state.get("turn_action_validation_feedback")
    if not isinstance(feedback_state, dict):
        return

    if session_id is not None and feedback_state.get("session_id") != session_id:
        return
    if turn_index is not None and feedback_state.get("turn_index") != turn_index:
        return
    if user_id is not None and feedback_state.get("user_id") != user_id:
        return

    st.session_state.pop("turn_action_validation_feedback", None)


def get_turn_action_validation_feedback(*, session_id, turn_index, user_id):
    feedback_state = st.session_state.get("turn_action_validation_feedback")
    if not isinstance(feedback_state, dict):
        return ""

    if feedback_state.get("session_id") != session_id:
        return ""
    if feedback_state.get("turn_index") != turn_index:
        return ""
    if feedback_state.get("user_id") != user_id:
        return ""

    return normalize_app_text(feedback_state.get("message"))


def render_turn_action_validation_feedback(
    container,
    *,
    session_id,
    turn_index,
    user_id,
    force=False
):
    feedback_message = get_turn_action_validation_feedback(
        session_id=session_id,
        turn_index=turn_index,
        user_id=user_id
    )
    if feedback_message == "":
        return

    signature = (session_id, turn_index, user_id, feedback_message)
    previous_signature = st.session_state.get("turn_action_validation_feedback_render_signature")
    if force or previous_signature != signature:
        log_turn_action_event(
            "turn_action_validation_feedback_rendered",
            session_id=session_id,
            turn_index=turn_index,
            user_id=user_id,
            feedback_preview=short_debug_preview(feedback_message)
        )
        st.session_state.turn_action_validation_feedback_render_signature = signature

    container.warning(feedback_message)


def add_ai_message_with_logging(
    *,
    branch_name,
    session_id,
    turn_index,
    user_id,
    role_name,
    sender,
    content,
    submit_trace_id=None
):
    normalized_content = normalize_app_text(content)
    log_ai_submit_event(
        "before_add_ai_message_call",
        submit_trace_id=submit_trace_id,
        branch_name=branch_name,
        session_id=session_id,
        turn_index=turn_index,
        user_id=user_id,
        role_name=role_name,
        sender=sender,
        content_type=type(normalized_content).__name__,
        content_length=len((normalized_content or "").strip())
    )
    try:
        row_id = add_ai_message(
            session_id=session_id,
            turn_index=turn_index,
            user_id=user_id,
            role_name=role_name,
            sender=sender,
            content=normalized_content
        )
    except Exception as exc:
        log_ai_submit_event(
            "add_ai_message_call_exception",
            submit_trace_id=submit_trace_id,
            branch_name=branch_name,
            exception_type=type(exc).__name__,
            exception_message=str(exc)
        )
        raise

    log_ai_submit_event(
        "after_add_ai_message_call",
        submit_trace_id=submit_trace_id,
        branch_name=branch_name,
        row_id=row_id
    )
    return row_id


def mark_ai_coach_submit_started():
    st.session_state.ai_coach_submit_in_progress = True
    st.session_state.ai_coach_force_reload = False
    st.session_state.ai_coach_force_reload_context = None


def queue_ai_coach_state_update(user_id, payload):
    if not user_id:
        return

    _pending_ai_coach_state_updates[user_id] = dict(payload)
    log_ai_submit_event(
        "queued_pending_ai_coach_state",
        submit_trace_id=payload.get("submit_trace_id"),
        pipeline_stage=payload.get("pipeline_stage"),
        ai_reply_saved=payload.get("ai_reply_saved")
    )


def flush_pending_ai_coach_state_update():
    user_id = st.session_state.get("user_id")
    if not user_id:
        return

    pending_payload = _pending_ai_coach_state_updates.pop(user_id, None)
    if not pending_payload:
        return

    log_ai_submit_event(
        "flushing_pending_ai_coach_state",
        submit_trace_id=pending_payload.get("submit_trace_id"),
        pipeline_stage=pending_payload.get("pipeline_stage"),
        ai_reply_saved=pending_payload.get("ai_reply_saved")
    )
    st.session_state.last_ai_coach_debug = dict(pending_payload)


# ---------- 1. 鍒濆鍖?session_state ----------
if "user_id" not in st.session_state:
    st.session_state.user_id = None

if "username" not in st.session_state:
    st.session_state.username = ""

if "room_id" not in st.session_state:
    st.session_state.room_id = None

if "invite_code" not in st.session_state:
    st.session_state.invite_code = None

if "last_ai_coach_debug" not in st.session_state:
    st.session_state.last_ai_coach_debug = None

if "ai_coach_submit_in_progress" not in st.session_state:
    st.session_state.ai_coach_submit_in_progress = False

if "ai_coach_force_reload" not in st.session_state:
    st.session_state.ai_coach_force_reload = False

if "ai_coach_force_reload_context" not in st.session_state:
    st.session_state.ai_coach_force_reload_context = None

inject_readability_styles()

show_ai_coach_debug = should_show_ai_coach_debug()
if (
    show_ai_coach_debug
    or st.session_state.get("ai_coach_force_reload") is True
    or st.session_state.get("ai_coach_submit_in_progress") is True
):
    log_ai_submit_event(
        "ai_coach_force_reload_on_script_start",
        force_reload_value=st.session_state.get("ai_coach_force_reload"),
        force_reload_type=type(st.session_state.get("ai_coach_force_reload")).__name__,
        force_reload_context_value=st.session_state.get("ai_coach_force_reload_context"),
        force_reload_context_type=type(st.session_state.get("ai_coach_force_reload_context")).__name__,
        ai_coach_submit_in_progress=st.session_state.get("ai_coach_submit_in_progress")
    )

flush_pending_ai_coach_state_update()
if show_ai_coach_debug:
    log_ai_submit_event(
        "app_script_loaded",
        runtime_marker=APP_RUNTIME_MARKER,
        app_file=__file__
    )


# ---------- 2. 浠?URL 鎭㈠鐢ㄦ埛韬唤 ----------
query_params = st.query_params

if st.session_state.user_id is None and "user_id" in query_params:
    st.session_state.user_id = query_params["user_id"]

if st.session_state.username == "" and "username" in query_params:
    st.session_state.username = query_params["username"]

if st.session_state.invite_code is None and "invite_code" in query_params:
    code_from_url = query_params["invite_code"]
    room = get_room_by_code(code_from_url)
    if room and st.session_state.user_id is not None:
        room_id_from_url = room[0]
        can_restore, _ = can_user_join_room(
            room_id_from_url,
            st.session_state.user_id
        )
        if can_restore:
            services.join_room(
                room_id_from_url, st.session_state.user_id,
                st.session_state.username, restore=True
            )
            st.session_state.invite_code = code_from_url
            st.session_state.room_id = room_id_from_url


def save_user_to_url():
    """鎶婂綋鍓嶇敤鎴疯韩浠藉拰鎴块棿淇℃伅鍐欏埌 URL锛屽埛鏂板悗杩樿兘淇濈暀"""
    if st.session_state.user_id:
        st.query_params["user_id"] = st.session_state.user_id
    if st.session_state.username:
        st.query_params["username"] = st.session_state.username
    if st.session_state.invite_code:
        st.query_params["invite_code"] = st.session_state.invite_code


def clear_url():
    """绂诲紑鎴块棿鏃舵竻绌?URL 鍙傛暟"""
    st.query_params.clear()


def ensure_user_created(username, mbti=None, priorities=None):
    """鍙湁绗竴娆℃墠鍒涘缓 user_id"""
    profile = services.create_profile(username, mbti, priorities, st.session_state.user_id)
    st.session_state.user_id = profile["user_id"]
    st.session_state.username = username
    save_user_to_url()


def get_current_stage_obj(current_session):
    """
    current_session uses the dictionary shape returned by database.get_session_by_room().
    """
    if current_session is None:
        return None

    stages = current_session.get("stages", [])
    current_stage_index = current_session.get("current_stage", 1)

    for stage in stages:
        if stage.get("stage_index") == current_stage_index:
            return stage

    return None


def get_stage_prompt_for_role(stage_obj, user_role):
    if not stage_obj:
        return ""

    if user_role == "role_a":
        return stage_obj.get("prompt_a", "")
    elif user_role == "role_b":
        return stage_obj.get("prompt_b", "")
    return ""


def generate_fake_ai_feedback(user_role, user_text, stage_index):
    """
    Temporary fallback feedback used for local development.
    """
    if user_role == "role_a":
        if stage_index == 1:
            return (
                "I can see that you are trying to balance pressure, standards, and emotion at the same time. "
                "Before reacting further, it may help to separate your immediate frustration from your longer-term goal in this relationship. "
                "What outcome are you actually trying to create with your next move?"
            )
        elif stage_index == 2:
            return (
                "The issue may not be only what you say next, but whether the other person can trust how you are making decisions. "
                "Which part of your next response is meant to repair the relationship, and which part is meant to clarify expectations?"
            )
        elif stage_index == 3:
            return (
                "The focus now is less about rescue and more about building a steadier pattern. "
                "What would help you stay calm in the first 30 seconds while still being clear about your standard or boundary?"
            )
        else:
            return "Please continue developing your reasoning."

    elif user_role == "role_b":
        if stage_index == 1:
            return (
                "You have already expressed hurt and unfairness. "
                "The next step may be to separate your emotional reaction from the communication strategy you want to use. "
                "If you want to be taken seriously without escalating the conflict, what fact or need do you most want to clarify first?"
            )
        elif stage_index == 2:
            return (
                "An apology may soften the emotion, but it does not always solve the underlying issue. "
                "What matters more to you now: how they evaluated you, how they spoke to you, or what boundary should change going forward?"
            )
        elif stage_index == 3:
            return (
                "A boundary is usually not one dramatic statement but a consistent pattern of response. "
                "How could you show that pressure-based communication does not work for you while still showing willingness to cooperate?"
            )
        else:
            return "Please continue explaining your thinking."

    return "Please continue sharing what you are thinking."


def get_stage_count(current_session):
    if current_session is None:
        return 0

    return len(current_session.get("stages", []))


WAITING_ROOM_REFRESH_INTERVAL_MS = 5000
ACTIVE_SESSION_IDLE_REFRESH_INTERVAL_MS = 5000
ACTIVE_SESSION_PENDING_REFRESH_INTERVAL_MS = 4000
room_refresh_interval_ms = ACTIVE_SESSION_IDLE_REFRESH_INTERVAL_MS
room_refresh_enabled = False


# ---------- 3. Welcome page ----------
if st.session_state.room_id is None:
    render_app_header(
        badge="Welcome",
        subtitle="Role-play decision training for difficult conversations"
    )

    existing_profile = get_user_profile(st.session_state.user_id)
    hero_left, hero_right = st.columns([1.08, 0.92], gap="large")

    with hero_left:
        with st.container(border=True):
            st.markdown('<div class="echorole-section-kicker">Profile setup</div>', unsafe_allow_html=True)
            st.markdown("**Start with your communication profile**")
            st.caption("This helps EchoRole keep the room grounded in your own values and style.")

            username_input = st.text_input(
                "Enter your username",
                value=st.session_state.username
            )
            mbti_input = st.text_input(
                "MBTI (optional)",
                value=existing_profile.get("mbti", "")
            )
            priorities_input = st.text_area(
                "Communication / value priorities (optional)",
                value=existing_profile.get("priorities", "")
            )

    with hero_right:
        with st.container(border=True):
            st.markdown('<div class="echorole-section-kicker">Create</div>', unsafe_allow_html=True)
            st.markdown("**Create a Room**")
            st.caption("Start a private practice space and invite another participant when you're ready.")
            if st.button("Create Room", key="welcome_create_room"):
                username_value = (username_input or "").strip()
                mbti_value = (mbti_input or "").strip()
                priorities_value = (priorities_input or "").strip()

                if username_value == "":
                    st.error("Please enter a username first.")
                else:
                    ensure_user_created(
                        username_value,
                        mbti=mbti_value,
                        priorities=priorities_value
                    )

                    room = services.create_room(
                        st.session_state.user_id, st.session_state.username,
                        sync=bump_room_sync_event
                    )
                    room_id, code = room["id"], room["invite_code"]

                    st.session_state.room_id = room_id
                    st.session_state.invite_code = code
                    save_user_to_url()
                    st.rerun()

        with st.container(border=True):
            st.markdown('<div class="echorole-section-kicker">Join</div>', unsafe_allow_html=True)
            st.markdown("**Join a Room**")
            st.caption("Already have an invite code? Join the room and continue from your own profile.")
            input_code = st.text_input("Enter invite code")

            if st.button("Join Room", key="welcome_join_room"):
                username_value = (username_input or "").strip()
                input_code_value = (input_code or "").strip()
                mbti_value = (mbti_input or "").strip()
                priorities_value = (priorities_input or "").strip()

                if username_value == "":
                    st.error("Please enter a username first.")
                else:
                    room = get_room_by_code(input_code_value)

                    if room:
                        ensure_user_created(
                            username_value,
                            mbti=mbti_value,
                            priorities=priorities_value
                        )

                        room_id = room[0]
                        invite_code = room[1]
                        can_join, join_reason = can_user_join_room(
                            room_id,
                            st.session_state.user_id
                        )

                        if not can_join:
                            st.error(join_reason)
                        else:
                            services.join_room(
                                room_id, st.session_state.user_id,
                                st.session_state.username, sync=bump_room_sync_event
                            )

                            st.session_state.room_id = room_id
                            st.session_state.invite_code = invite_code
                            save_user_to_url()
                            st.rerun()
                    else:
                        st.error("Invalid invite code")

# ---------- 4. Room / Session ----------
else:
    user_profile = get_user_profile(st.session_state.user_id)
    current_user_total_points = get_total_received_peer_feedback_points(st.session_state.user_id)
    members = get_members_by_room(st.session_state.room_id)
    current_session = get_session_by_room(st.session_state.room_id)
    current_session_id_for_sync = current_session["id"] if current_session is not None else None
    check_room_sync_event_version(
        room_id=st.session_state.room_id,
        session_id=current_session_id_for_sync,
        force=should_show_ai_coach_debug()
    )
    refresh_members_clicked = False
    leave_room_clicked = False
    waiting_left_col = None
    waiting_right_col = None
    room_refresh_reason = "disabled"

    if current_session is None:
        room_refresh_enabled = True
        room_refresh_interval_ms = WAITING_ROOM_REFRESH_INTERVAL_MS
        room_refresh_reason = "waiting_room_lobby"
        render_app_header(
            badge="Room Lobby",
            subtitle="Gather your profile, review who is here, and choose the scenario when everyone is ready.",
            supporting_text="The room is open. You can update your profile, check who joined, and prepare the next session together.",
            room_code=st.session_state.invite_code
        )
        waiting_left_col, waiting_right_col = st.columns([1.02, 1.38], gap="large")

        with waiting_left_col:
            render_profile_card(user_profile, "unassigned", total_points=current_user_total_points)
            render_profile_editor(user_profile)
            render_room_info_card(
                invite_code=st.session_state.invite_code,
                username=st.session_state.username,
                user_id=st.session_state.user_id
            )
            render_members_card(members)
            with st.container(border=True):
                st.markdown('<div class="echorole-section-kicker">Room actions</div>', unsafe_allow_html=True)
                st.markdown("**Room Controls**")
                st.caption("Refresh the room list if someone just joined, or leave the room when you are done.")
                refresh_members_clicked = st.button(
                    "Refresh Members",
                    key="waiting_refresh_members_card"
                )
                leave_room_clicked = st.button(
                    "Leave Room",
                    key="waiting_leave_room_card"
                )

        with waiting_right_col:
            with st.container(border=True):
                st.markdown('<div class="echorole-section-kicker">Scenario setup</div>', unsafe_allow_html=True)
                st.markdown("**Choose a Scenario**")
                st.caption("Pick the conflict you want to practice before launching the active session.")

                scenario_categories = get_scenario_categories()
                selected_category = st.selectbox(
                    "Scenario category",
                    options=scenario_categories,
                    key="scenario_category_selector"
                )

                category_scenarios = get_scenarios_by_category(selected_category)
                scenario_options = {
                    scenario["title"]: scenario["id"]
                    for scenario in category_scenarios
                }
                selected_title = st.selectbox(
                    "Scenario title",
                    options=list(scenario_options.keys()),
                    key="scenario_title_selector"
                )

                selected_scenario = get_scenario_by_id(scenario_options[selected_title])

                if selected_scenario is not None:
                    st.caption(f"Category: {selected_scenario['category']}")
                    st.write("**Context:**", selected_scenario["context"])
                    st.write("**Conflict:**", selected_scenario["conflict"])
                    st.write("**Opening Situation:**", selected_scenario["opening_situation"])

                if st.button(
                    "Create Scenario Session",
                    key="waiting_create_scenario_session"
                ):
                    if selected_scenario is None:
                        st.error("Please choose a scenario before creating a session.")
                    else:
                        services.create_scenario_session(
                            st.session_state.room_id, selected_scenario,
                            sync=bump_room_sync_event
                        )
                        st.rerun()

    else:
        inject_active_session_dashboard_styles()
        render_app_header(
            dashboard=True,
            badge="Active Session",
            subtitle="Move through the current conflict one turn at a time, with private coaching and shared action.",
            supporting_text="Use the middle column to reflect with AI Coach, and the right column to decide how your character acts next.",
            room_code=st.session_state.invite_code
        )
        session_id = current_session["id"]
        scenario_title = current_session["title"]
        scenario_context = current_session["context"]
        conflict = current_session["conflict"]
        role_a_brief = current_session["role_a_brief"]
        role_b_brief = current_session["role_b_brief"]
        current_turn = current_session["current_turn"]
        left_col, middle_col, right_col = st.columns([1.05, 1.8, 1.22], gap="large")

        user_role = get_user_role(session_id, st.session_state.user_id)

        if user_role is None:
            try:
                services.ensure_role(session_id, st.session_state.user_id)
            except services.ApplicationError as exc:
                st.error(str(exc))
                st.stop()
            st.rerun()

        user_role = get_user_role(session_id, st.session_state.user_id)

        private_role_brief = ""
        if user_role == "role_a":
            private_role_brief = role_a_brief
        elif user_role == "role_b":
            private_role_brief = role_b_brief
        else:
            st.warning("Your role has not been assigned yet.")

        recent_turn_history = get_turn_history(session_id)[-3:]
        latest_story_state = get_latest_story_state(session_id)
        recent_story_states = get_recent_story_states(session_id, limit=3)
        current_story_state = None
        if latest_story_state is not None and latest_story_state.get("turn_index") == current_turn:
            current_story_state = latest_story_state

        current_situation = normalize_app_text(
            (current_story_state or {}).get("shared_situation")
            or current_session["current_situation"]
        )
        current_role_perspective = ""
        if current_story_state is not None:
            if user_role == "role_a":
                current_role_perspective = normalize_app_text(
                    current_story_state.get("role_a_perspective")
                )
            elif user_role == "role_b":
                current_role_perspective = normalize_app_text(
                    current_story_state.get("role_b_perspective")
                )
        current_next_decision_point = normalize_app_text(
            (current_story_state or {}).get("next_decision_point")
        )
        current_role_brief_history = get_role_brief_history(session_id, user_role)
        role_brief_history_signature = (
            session_id,
            user_role,
            tuple(
                (entry.get("turn_number"), normalize_app_text(entry.get("brief_text")))
                for entry in current_role_brief_history
            ),
        )
        previous_role_brief_history_signature = st.session_state.get("role_brief_history_loaded_signature")
        if previous_role_brief_history_signature != role_brief_history_signature:
            log_turn_action_event(
                "role_brief_history_loaded",
                session_id=session_id,
                turn_index=current_turn,
                role_name=user_role,
                history_count=len(current_role_brief_history),
                latest_turn_number=(
                    current_role_brief_history[-1].get("turn_number")
                    if current_role_brief_history else None
                )
            )
            st.session_state.role_brief_history_loaded_signature = role_brief_history_signature

        if current_role_brief_history:
            private_role_brief = normalize_app_text(
                current_role_brief_history[-1].get("brief_text")
            )

        evolved_current_session = dict(current_session)
        if user_role == "role_a" and private_role_brief:
            evolved_current_session["role_a_brief"] = private_role_brief
            evolved_current_session["role_a_brief_history_entries"] = current_role_brief_history
        elif user_role == "role_b" and private_role_brief:
            evolved_current_session["role_b_brief"] = private_role_brief
            evolved_current_session["role_b_brief_history_entries"] = current_role_brief_history
        current_user_turn_suggestion = normalize_app_text(
            get_turn_suggestion(session_id, current_turn, user_role)
        )
        if current_user_turn_suggestion:
            log_turn_action_event(
                "ai_suggestion_loaded_for_current_user",
                session_id=session_id,
                turn_index=current_turn,
                role_name=user_role,
                suggestion_preview=short_debug_preview(current_user_turn_suggestion)
            )
        turn_prompt = build_turn_coach_prompt(
            evolved_current_session,
            user_role,
            user_profile=user_profile,
            recent_turn_history=recent_turn_history
        )
        raw_recent_ai_coach_history = get_recent_ai_messages_for_user(
            session_id=session_id,
            user_id=st.session_state.user_id,
            limit=16
        )
        recent_ai_coach_history = get_visible_ai_coach_history_entries(
            raw_recent_ai_coach_history,
            hidden_ai_prompt_content=turn_prompt,
            limit=8,
            session_id=session_id,
            user_id=st.session_state.user_id,
            turn_index=current_turn
        )

        with left_col:
            render_profile_card(user_profile, user_role, total_points=current_user_total_points)
            render_profile_editor(user_profile)
            render_room_info_card(
                invite_code=st.session_state.invite_code,
                username=st.session_state.username,
                user_id=st.session_state.user_id
            )
            render_members_card(members)
            render_scenario_overview_cards(
                scenario_title=scenario_title,
                scenario_context=scenario_context,
                conflict=conflict,
                current_turn=current_turn,
                show_current_situation=False
            )
            render_peer_feedback_card(
                room_id=st.session_state.room_id,
                session_id=session_id,
                current_turn=current_turn,
                current_user_id=st.session_state.user_id,
                other_member=get_other_room_member(members, st.session_state.user_id)
            )
            refresh_members_clicked = st.button(
                "Refresh Members",
                key="active_refresh_members"
            )
            leave_room_clicked = st.button(
                "Leave Room",
                key="active_leave_room"
            )

        with middle_col:
            render_current_situation_feature_card(current_situation)
            story_render_signature = (
                session_id,
                current_turn,
                (current_story_state or {}).get("id"),
                current_situation,
                current_role_perspective,
                current_next_decision_point,
            )
            previous_story_render_signature = st.session_state.get("story_progression_render_signature")
            if previous_story_render_signature != story_render_signature:
                log_turn_action_event(
                    "story_progression_rendered",
                    session_id=session_id,
                    previous_turn_index=max(1, current_turn - 1),
                    new_turn_index=current_turn,
                    shared_chat_message_count=len(get_recent_shared_chat_messages(session_id, limit=6)),
                    progression_history_count=len(recent_story_states),
                    shared_situation_preview=short_debug_preview(current_situation),
                    next_decision_point_preview=short_debug_preview(current_next_decision_point),
                )
                st.session_state.story_progression_render_signature = story_render_signature
            if current_role_perspective:
                render_text_card(
                    "Your Current Pressure",
                    current_role_perspective,
                    caption="Private to your role in this stage."
                )
            if current_next_decision_point:
                render_text_card(
                    "Next Decision Point",
                    current_next_decision_point,
                    caption="This is the shared tension the next turn is testing."
                )
            st.subheader("AI Coach Chat")
            render_role_brief_history_card(user_role, current_role_brief_history)
            for entry in current_role_brief_history:
                render_signature = (
                    session_id,
                    user_role,
                    entry.get("turn_number"),
                    normalize_app_text(entry.get("brief_text"))
                )
                rendered_signatures = set(st.session_state.get("role_brief_turn_render_signatures") or [])
                if render_signature not in rendered_signatures:
                    log_turn_action_event(
                        "role_brief_turn_rendered",
                        session_id=session_id,
                        turn_index=current_turn,
                        role_name=user_role,
                        brief_turn_number=entry.get("turn_number"),
                        brief_preview=short_debug_preview(entry.get("brief_text"))
                    )
                    rendered_signatures.add(render_signature)
                    st.session_state.role_brief_turn_render_signatures = list(rendered_signatures)

        # 绗竴娆¤繘鍏ュ綋鍓?stage 鏃讹紝鑷姩鍐欏叆棣栨潯 AI prompt
        if user_role is not None and not has_ai_prompt_for_turn(
            session_id,
            current_turn,
            st.session_state.user_id
        ):
            if (turn_prompt or "").strip():
                add_ai_message_with_logging(
                    branch_name="turn_prompt_autoinsert",
                    session_id=session_id,
                    turn_index=current_turn,
                    user_id=st.session_state.user_id,
                    role_name=user_role,
                    sender="ai",
                    content=turn_prompt
                )
                st.rerun()

        ai_messages = get_ai_messages(
            session_id=session_id,
            turn_index=current_turn,
            user_id=st.session_state.user_id
        )
        ai_messages_container = middle_col.empty()
        pending_submit_trace_id = (
            (st.session_state.get("last_ai_coach_debug") or {}).get("submit_trace_id")
        )
        if st.session_state.ai_coach_submit_in_progress:
            log_ai_submit_event(
                "ai_messages_reloaded_for_top_level_render",
                submit_trace_id=pending_submit_trace_id,
                loaded_message_count=len(ai_messages),
                loaded_ai_message_count=sum(
                    1 for msg in ai_messages if msg[0] == "ai"
                )
            )

        ai_coach_debug = get_visible_ai_coach_debug(
            session_id=session_id,
            user_id=st.session_state.user_id,
            current_turn=current_turn
        )
        show_ai_coach_debug = should_show_ai_coach_debug()
        if ai_coach_debug is not None:
            ai_coach_debug = dict(ai_coach_debug)
            if ai_coach_debug.get("is_current_turn_snapshot"):
                ai_coach_debug["rendered_message_count"] = len(ai_messages)
                ai_coach_debug["rendered_ai_message_count"] = sum(
                    1 for msg in ai_messages if msg[0] == "ai"
                )
            st.session_state.last_ai_coach_debug = ai_coach_debug
            log_ai_submit_event(
                "rendering_ai_messages",
                submit_trace_id=ai_coach_debug.get("submit_trace_id"),
                rendered_message_count=ai_coach_debug.get("rendered_message_count"),
                rendered_ai_message_count=ai_coach_debug.get("rendered_ai_message_count"),
                pipeline_stage=ai_coach_debug.get("pipeline_stage")
            )

        render_ai_coach_messages(
            ai_messages_container,
            ai_messages,
            submit_trace_id=(
                pending_submit_trace_id
                if st.session_state.ai_coach_submit_in_progress
                else None
            ),
            hidden_ai_prompt_content=turn_prompt
        )
        if st.session_state.ai_coach_submit_in_progress:
            log_ai_submit_event(
                "ai_messages_rendered_from_db",
                submit_trace_id=pending_submit_trace_id,
                rendered_message_count=len(ai_messages),
                rendered_ai_message_count=sum(
                    1 for msg in ai_messages if msg[0] == "ai"
                )
            )
            if len(ai_messages) > 0 and ai_messages[-1][0] == "ai":
                st.session_state.ai_coach_submit_in_progress = False
                log_ai_submit_event(
                    "ai_coach_submit_in_progress_cleared_on_clean_render",
                    submit_trace_id=pending_submit_trace_id,
                    latest_sender=ai_messages[-1][0]
                )

        if show_ai_coach_debug and ai_coach_debug is not None:
            with middle_col.expander("Coach Reply Debug", expanded=False):
                st.caption(f"Submit stage: {ai_coach_debug.get('pipeline_stage', '(unknown)')}")
                st.caption(f"Submit in progress: {st.session_state.ai_coach_submit_in_progress}")
                st.caption(f"Submit trace id: {ai_coach_debug.get('submit_trace_id', '(unknown)')}")
                st.caption(f"Debug snapshot turn: {ai_coach_debug.get('turn_index', '(unknown)')}")
                st.caption(f"Provider path: {ai_coach_debug.get('provider', 'unknown')}")
                st.caption(f"Provider stage: {ai_coach_debug.get('provider_stage', '(unknown)')}")
                st.caption(f"DeepSeek call succeeded: {ai_coach_debug.get('llm_call_succeeded', False)}")
                st.caption(f"HTTP status: {ai_coach_debug.get('llm_http_status', '(none)')}")
                st.caption(f"HTTP timeout seconds: {ai_coach_debug.get('llm_timeout_seconds', '(unknown)')}")
                st.caption(f"Reply extracted: {ai_coach_debug.get('reply_extracted', False)}")
                st.caption(f"Response content type: {ai_coach_debug.get('content_type', '(unknown)')}")
                st.caption(f"Fallback used: {ai_coach_debug.get('used_fallback', False)}")
                st.caption(f"Fallback reason: {ai_coach_debug.get('fallback_reason', '') or '(none)'}")
                st.caption(f"Saved to ai_messages: {ai_coach_debug.get('ai_reply_saved', False)}")
                st.caption(f"Saved AI row id: {ai_coach_debug.get('ai_reply_message_id', '(none)')}")
                st.caption(f"Messages loaded immediately after save: {ai_coach_debug.get('loaded_message_count_after_save', 0)}")
                st.caption(f"AI messages loaded immediately after save: {ai_coach_debug.get('loaded_ai_message_count_after_save', 0)}")
                st.caption(f"Rendered messages this turn: {ai_coach_debug.get('rendered_message_count', 0)}")
                st.caption(f"Rendered AI messages this turn: {ai_coach_debug.get('rendered_ai_message_count', 0)}")
                st.caption(f"Extracted reply length: {ai_coach_debug.get('reply_length', 0)}")
                st.caption(f"Extracted reply preview: {ai_coach_debug.get('reply_preview', '') or '(empty)'}")
                st.caption(f"Saved reply preview: {ai_coach_debug.get('saved_reply_preview', '') or '(empty)'}")
                if ai_coach_debug.get("pipeline_error"):
                    st.caption(f"Pipeline error: {ai_coach_debug.get('pipeline_error')}")

        with middle_col.form("ai_chat_form", clear_on_submit=True):
            ai_input = st.text_area("Reply to AI")
            ai_submit = st.form_submit_button(
                "Send to AI",
                on_click=mark_ai_coach_submit_started
            )

            if ai_submit:
                ai_input_value = (ai_input or "").strip()

                if ai_input_value == "":
                    st.session_state.ai_coach_submit_in_progress = False
                    st.error("AI reply cannot be empty.")
                else:
                    submit_user_id = st.session_state.user_id
                    submit_trace_id = str(uuid.uuid4())[:8]
                    log_ai_submit_event(
                        "ai_coach_submit_started",
                        submit_trace_id=submit_trace_id,
                        session_id=session_id,
                        turn_index=current_turn,
                        user_id=submit_user_id
                    )
                    base_debug_snapshot = {
                        "session_id": session_id,
                        "turn_index": current_turn,
                        "user_id": submit_user_id,
                        "submit_trace_id": submit_trace_id,
                        "provider": "pending",
                        "provider_stage": "not_started",
                        "llm_call_attempted": False,
                        "llm_call_succeeded": False,
                        "llm_http_status": None,
                        "llm_timeout_seconds": None,
                        "reply_extracted": False,
                        "reply_length": 0,
                        "reply_preview": "",
                        "content_type": "pending",
                        "used_fallback": False,
                        "fallback_reason": "",
                        "ai_reply_saved": False,
                        "ai_reply_message_id": None,
                        "saved_reply_preview": "",
                        "saved_reply_length": 0,
                        "loaded_message_count_after_save": 0,
                        "loaded_ai_message_count_after_save": 0,
                        "rendered_message_count": len(ai_messages),
                        "rendered_ai_message_count": sum(
                            1 for msg in ai_messages if msg[0] == "ai"
                        ),
                        "pipeline_stage": "submit_clicked",
                        "pipeline_error": "",
                        "submitted_reflection_preview": short_debug_preview(ai_input_value),
                    }
                    st.session_state.ai_coach_submit_in_progress = True
                    st.session_state.ai_coach_force_reload = False
                    st.session_state.ai_coach_force_reload_context = None
                    st.session_state.last_ai_coach_debug = dict(base_debug_snapshot)

                    user_message_id = None
                    ai_reply_message_id = None
                    ai_feedback = ""
                    engine_debug_info = {}
                    post_return_debug_snapshot = None

                    try:
                        log_ai_submit_event(
                            "saving_user_message",
                            submit_trace_id=submit_trace_id,
                            session_id=session_id,
                            turn_index=current_turn
                        )
                        update_ai_coach_debug_snapshot(pipeline_stage="saving_user_message")
                        user_message_id = add_ai_message(
                            session_id=session_id,
                            turn_index=current_turn,
                            user_id=submit_user_id,
                            role_name=user_role,
                            sender="user",
                            content=ai_input_value
                        )
                        log_ai_submit_event(
                            "user_message_saved",
                            submit_trace_id=submit_trace_id,
                            user_message_id=user_message_id
                        )
                        update_ai_coach_debug_snapshot(
                            pipeline_stage="user_message_saved",
                            user_message_id=user_message_id
                        )

                        log_ai_submit_event(
                            "calling_generate_dynamic_ai_feedback",
                            submit_trace_id=submit_trace_id,
                            reflection_length=len(ai_input_value)
                        )
                        update_ai_coach_debug_snapshot(
                            pipeline_stage="calling_generate_dynamic_ai_feedback"
                        )
                        thinking_status = None
                        try:
                            log_ai_submit_event(
                                "before_entering_spinner",
                                submit_trace_id=submit_trace_id
                            )
                            thinking_status = middle_col.empty()
                            thinking_status.caption("AI Coach is thinking...")
                            log_ai_submit_event(
                                "after_entering_spinner",
                                submit_trace_id=submit_trace_id
                            )
                            log_ai_submit_event(
                                "before_generate_dynamic_ai_feedback_call",
                                submit_trace_id=submit_trace_id
                            )
                            latest_user_profile = get_user_profile(submit_user_id)
                            log_ai_submit_event(
                                "ai_coach_profile_loaded_for_submit",
                                submit_trace_id=submit_trace_id,
                                profile_updated_at=(latest_user_profile or {}).get("updated_at"),
                                profile_preview=short_debug_preview(
                                    normalize_app_text(
                                        (latest_user_profile or {}).get("priorities")
                                    )
                                )
                            )
                            log_ai_submit_event(
                                "ai_coach_history_loaded_for_submit",
                                submit_trace_id=submit_trace_id,
                                ai_coach_history_message_count=len(recent_ai_coach_history),
                                latest_history_sender=(
                                    recent_ai_coach_history[-1]["sender"]
                                    if recent_ai_coach_history
                                    else ""
                                )
                            )
                            ai_feedback = generate_dynamic_ai_feedback(
                                user_role=user_role,
                                user_text=ai_input_value,
                                current_turn=current_turn,
                                current_situation=current_situation,
                                current_session=current_session,
                                user_profile=latest_user_profile,
                                recent_turn_history=recent_turn_history,
                                recent_coach_history=recent_ai_coach_history,
                                debug_trace_id=submit_trace_id
                            )
                            log_ai_submit_event(
                                "after_generate_dynamic_ai_feedback_call",
                                submit_trace_id=submit_trace_id,
                                reply_type=type(ai_feedback).__name__
                            )
                        except BaseException as exc:
                            post_call_error = f"{type(exc).__name__}: {exc}"
                            log_ai_submit_event(
                                "ai_feedback_post_call_exception",
                                submit_trace_id=submit_trace_id,
                                exception_type=type(exc).__name__,
                                exception_message=str(exc),
                                boundary="generate_dynamic_ai_feedback"
                            )
                            queue_ai_coach_state_update(
                                submit_user_id,
                                {
                                    **base_debug_snapshot,
                                    "pipeline_stage": "ai_feedback_post_call_exception",
                                    "pipeline_error": post_call_error,
                                    "user_message_id": user_message_id,
                                }
                            )
                            raise
                        log_ai_submit_event(
                            "before_ai_feedback_returned_log",
                            submit_trace_id=submit_trace_id
                        )
                        ai_feedback = normalize_app_text(ai_feedback)
                        log_ai_submit_event(
                            "ai_feedback_returned",
                            submit_trace_id=submit_trace_id,
                            reply_length=len((ai_feedback or "").strip()),
                            reply_type=type(ai_feedback).__name__
                        )
                        post_return_debug_snapshot = {
                            **base_debug_snapshot,
                            "pipeline_stage": "ai_feedback_returned",
                            "user_message_id": user_message_id,
                            "saved_reply_preview": short_debug_preview(ai_feedback),
                            "saved_reply_length": len((ai_feedback or "").strip()),
                        }
                        log_ai_submit_event(
                            "post_return_debug_buffered",
                            submit_trace_id=submit_trace_id,
                            reply_length=post_return_debug_snapshot["saved_reply_length"]
                        )

                        log_ai_submit_event(
                            "capturing_engine_debug",
                            submit_trace_id=submit_trace_id
                        )
                        engine_debug_info = get_last_ai_debug_info()
                        log_ai_submit_event(
                            "engine_debug_captured",
                            submit_trace_id=submit_trace_id,
                            engine_provider=engine_debug_info.get("provider"),
                            engine_provider_stage=engine_debug_info.get("provider_stage"),
                            engine_reply_length=engine_debug_info.get("reply_length")
                        )
                        post_return_debug_snapshot.update(engine_debug_info)
                        post_return_debug_snapshot.update({
                            "pipeline_stage": "updating_debug_snapshot",
                            "saved_reply_preview": short_debug_preview(ai_feedback),
                            "saved_reply_length": len((ai_feedback or "").strip()),
                        })
                        log_ai_submit_event(
                            "debug_snapshot_updated",
                            submit_trace_id=submit_trace_id,
                            provider=post_return_debug_snapshot.get("provider"),
                            provider_stage=post_return_debug_snapshot.get("provider_stage")
                        )

                        log_ai_submit_event(
                            "saving_ai_reply",
                            submit_trace_id=submit_trace_id
                        )
                        log_ai_submit_event(
                            "after_saving_ai_reply_marker",
                            submit_trace_id=submit_trace_id
                        )
                        try:
                            post_return_debug_snapshot["pipeline_stage"] = "saving_ai_reply"
                            log_ai_submit_event(
                                "after_setting_saving_ai_reply_stage",
                                submit_trace_id=submit_trace_id,
                                pipeline_stage=post_return_debug_snapshot.get("pipeline_stage")
                            )
                            log_ai_submit_event(
                                "before_coach_reply_save_branch_context",
                                submit_trace_id=submit_trace_id
                            )
                            coach_reply_save_branch_name = "coach_reply_save_v3"
                            log_ai_submit_event(
                                "after_coach_reply_save_branch_name",
                                submit_trace_id=submit_trace_id,
                                branch_name=coach_reply_save_branch_name
                            )
                            coach_reply_save_branch_context = {}

                            def assign_coach_reply_context_field(field_name, value_factory):
                                log_ai_submit_event(
                                    f"context_field_{field_name}",
                                    submit_trace_id=submit_trace_id
                                )
                                try:
                                    field_value = value_factory()
                                    coach_reply_save_branch_context[field_name] = field_value
                                    return field_value
                                except BaseException as exc:
                                    field_error = f"{type(exc).__name__}: {exc}"
                                    if isinstance(post_return_debug_snapshot, dict):
                                        post_return_debug_snapshot.update({
                                            "pipeline_stage": "coach_reply_branch_context_field_exception",
                                            "pipeline_error": f"{field_name}: {field_error}",
                                            "saved_reply_preview": short_debug_preview(ai_feedback),
                                            "saved_reply_length": len((ai_feedback or "").strip()),
                                            "context_field_name": field_name,
                                        })
                                        queue_ai_coach_state_update(
                                            submit_user_id,
                                            post_return_debug_snapshot
                                        )
                                    log_ai_submit_event(
                                        "coach_reply_branch_context_field_exception",
                                        submit_trace_id=submit_trace_id,
                                        field_name=field_name,
                                        exception_type=type(exc).__name__,
                                        exception_message=str(exc)
                                    )
                                    raise

                            assign_coach_reply_context_field(
                                "runtime_marker",
                                lambda: APP_RUNTIME_MARKER
                            )
                            assign_coach_reply_context_field(
                                "branch_name",
                                lambda: coach_reply_save_branch_name
                            )
                            assign_coach_reply_context_field(
                                "session_id",
                                lambda: session_id
                            )
                            assign_coach_reply_context_field(
                                "turn_index",
                                lambda: current_turn
                            )
                            assign_coach_reply_context_field(
                                "user_id",
                                lambda: submit_user_id
                            )
                            assign_coach_reply_context_field(
                                "role_name",
                                lambda: user_role
                            )
                            assign_coach_reply_context_field(
                                "sender",
                                lambda: "ai"
                            )
                            assign_coach_reply_context_field(
                                "ai_feedback_type",
                                lambda: type(ai_feedback).__name__
                            )
                            assign_coach_reply_context_field(
                                "ai_feedback_length",
                                lambda: len((ai_feedback or "").strip())
                            )
                            log_ai_submit_event(
                                "after_coach_reply_save_branch_context",
                                submit_trace_id=submit_trace_id,
                                branch_name=coach_reply_save_branch_context.get("branch_name"),
                                context_user_id=coach_reply_save_branch_context.get("user_id"),
                                ai_feedback_length=coach_reply_save_branch_context.get("ai_feedback_length")
                            )
                            log_ai_submit_event(
                                "before_active_ai_reply_save_branch_entered",
                                submit_trace_id=submit_trace_id,
                                branch_name=coach_reply_save_branch_name
                            )
                        except Exception as exc:
                            pre_save_boundary_error = f"{type(exc).__name__}: {exc}"
                            if isinstance(post_return_debug_snapshot, dict):
                                post_return_debug_snapshot.update({
                                    "pipeline_stage": "coach_reply_branch_context_exception",
                                    "pipeline_error": pre_save_boundary_error,
                                    "saved_reply_preview": short_debug_preview(ai_feedback),
                                    "saved_reply_length": len((ai_feedback or "").strip()),
                                })
                            log_ai_submit_event(
                                "coach_reply_branch_context_exception",
                                submit_trace_id=submit_trace_id,
                                exception_type=type(exc).__name__,
                                exception_message=str(exc)
                            )
                            raise
                        log_ai_submit_event(
                            "active_ai_reply_save_branch_entered",
                            submit_trace_id=submit_trace_id,
                            **coach_reply_save_branch_context
                        )
                        try:
                            ai_reply_message_id = add_ai_message_with_logging(
                                branch_name="coach_reply_save_v3",
                                session_id=session_id,
                                turn_index=current_turn,
                                user_id=submit_user_id,
                                role_name=user_role,
                                sender="ai",
                                content=ai_feedback
                            )
                        except Exception as exc:
                            add_ai_message_error = f"{type(exc).__name__}: {exc}"
                            post_return_debug_snapshot.update({
                                "pipeline_stage": "add_ai_message_call_exception",
                                "pipeline_error": add_ai_message_error,
                                "saved_reply_preview": short_debug_preview(ai_feedback),
                                "saved_reply_length": len((ai_feedback or "").strip()),
                            })
                            log_ai_submit_event(
                                "add_ai_message_call_exception",
                                submit_trace_id=submit_trace_id,
                                exception_type=type(exc).__name__,
                                exception_message=str(exc)
                            )
                            raise
                        log_ai_submit_event(
                            "ai_reply_saved",
                            submit_trace_id=submit_trace_id,
                            ai_reply_message_id=ai_reply_message_id
                        )
                        post_return_debug_snapshot.update({
                            "pipeline_stage": "ai_reply_saved",
                            "ai_reply_message_id": ai_reply_message_id,
                            "ai_reply_saved": ai_reply_message_id is not None,
                        })

                        log_ai_submit_event(
                            "reloading_ai_messages",
                            submit_trace_id=submit_trace_id
                        )
                        post_return_debug_snapshot["pipeline_stage"] = "reloading_ai_messages"
                        saved_ai_messages = get_ai_messages(
                            session_id=session_id,
                            turn_index=current_turn,
                            user_id=submit_user_id
                        )
                        loaded_ai_message_count = sum(
                            1 for msg in saved_ai_messages if msg[0] == "ai"
                        )
                        log_ai_submit_event(
                            "ai_messages_reloaded",
                            submit_trace_id=submit_trace_id,
                            loaded_message_count=len(saved_ai_messages),
                            loaded_ai_message_count=loaded_ai_message_count
                        )
                        post_return_debug_snapshot.update({
                            "pipeline_stage": "ai_messages_reloaded",
                            "user_message_id": user_message_id,
                            "ai_reply_message_id": ai_reply_message_id,
                            "ai_reply_saved": ai_reply_message_id is not None,
                            "saved_reply_preview": short_debug_preview(ai_feedback),
                            "saved_reply_length": len((ai_feedback or "").strip()),
                            "loaded_message_count_after_save": len(saved_ai_messages),
                            "loaded_ai_message_count_after_save": loaded_ai_message_count,
                        })
                        log_ai_submit_event(
                            "ai_coach_post_save_rerun_called",
                            submit_trace_id=submit_trace_id
                        )
                        st.rerun()
                    except Exception as exc:
                        exception_message = f"{type(exc).__name__}: {exc}"
                        exception_stage = (
                            (post_return_debug_snapshot or {}).get("pipeline_stage")
                            or "exception"
                        )
                        log_ai_submit_event(
                            "exception",
                            submit_trace_id=submit_trace_id,
                            pipeline_error=exception_message,
                            user_message_id=user_message_id,
                            ai_reply_message_id=ai_reply_message_id,
                            pipeline_stage=exception_stage
                        )
                        exception_snapshot = {
                            **(post_return_debug_snapshot or base_debug_snapshot),
                            **engine_debug_info,
                            "user_message_id": user_message_id,
                            "ai_reply_message_id": ai_reply_message_id,
                            "ai_reply_saved": False,
                            "saved_reply_preview": short_debug_preview(ai_feedback),
                            "saved_reply_length": len((ai_feedback or "").strip()),
                            "pipeline_stage": exception_stage,
                            "pipeline_error": exception_message,
                        }
                        queue_ai_coach_state_update(
                            submit_user_id,
                            exception_snapshot
                        )
                        st.session_state.ai_coach_submit_in_progress = False

        with middle_col:
            render_coach_reflection_prompt_card()
            render_recent_progression_history_card(recent_turn_history)

        with right_col:
            render_ai_suggestion_card(current_user_turn_suggestion)
        if current_user_turn_suggestion:
            log_turn_action_event(
                "ai_suggestion_rendered_for_current_user",
                session_id=session_id,
                turn_index=current_turn,
                role_name=user_role
            )

        pending_turn_state = load_pending_turn_state(
            session_id=session_id,
            turn_index=current_turn,
            current_user_id=st.session_state.user_id
        )
        active_pending_actions = pending_turn_state["active_pending_actions"]
        current_user_pending_action = pending_turn_state["current_user_pending_action"]
        other_pending_action = pending_turn_state["other_pending_action"]
        other_participant_submitted = pending_turn_state["other_participant_submitted"]
        actions_by_role = pending_turn_state["actions_by_role"]
        render_waiting_for_generation = False

        both_pending_actions_ready_for_render = (
            len(active_pending_actions) >= 2
            and "role_a" in actions_by_role
            and "role_b" in actions_by_role
            and (actions_by_role.get("role_a") or {}).get("status") == "pending"
            and (actions_by_role.get("role_b") or {}).get("status") == "pending"
        )
        if both_pending_actions_ready_for_render and not has_completed_turn(session_id, current_turn):
            render_trace_id = f"render-{str(uuid.uuid4())[:8]}"
            try:
                log_turn_action_event(
                    "pending_turn_actions_both_ready_from_render",
                    submit_trace_id=render_trace_id,
                    session_id=session_id,
                    turn_index=current_turn
                )
                log_turn_action_event(
                    "pending_turn_actions_claim_attempted_from_render",
                    submit_trace_id=render_trace_id,
                    session_id=session_id,
                    turn_index=current_turn
                )
                claim_result = claim_pending_turn_actions_for_generation(
                    session_id=session_id,
                    turn_index=current_turn
                )
                claim_status = claim_result.get("status")

                if claim_status == "already_completed":
                    mark_pending_turn_actions_consumed(session_id, current_turn)
                    log_turn_action_event(
                        "joint_turn_already_completed_skip_generation",
                        submit_trace_id=render_trace_id,
                        session_id=session_id,
                        turn_index=current_turn
                    )
                    st.info("This turn already advanced. Reloading the latest scenario state.")
                    st.rerun()

                if claim_status == "ready":
                    log_turn_action_event(
                        "pending_turn_actions_claim_succeeded_from_render",
                        submit_trace_id=render_trace_id,
                        session_id=session_id,
                        turn_index=current_turn
                    )
                    progression_completed = process_claimed_joint_turn(
                        session_id=session_id,
                        current_turn=current_turn,
                        submit_room_id=st.session_state.room_id,
                        evolved_current_session=evolved_current_session,
                        recent_turn_history=recent_turn_history,
                        actions_by_role=claim_result.get("actions") or {},
                        submit_trace_id=render_trace_id,
                        trigger_source="render"
                    )
                    if progression_completed is False:
                        pending_turn_state = load_pending_turn_state(
                            session_id=session_id,
                            turn_index=current_turn,
                            current_user_id=st.session_state.user_id
                        )
                        active_pending_actions = pending_turn_state["active_pending_actions"]
                        current_user_pending_action = pending_turn_state["current_user_pending_action"]
                        other_pending_action = pending_turn_state["other_pending_action"]
                        other_participant_submitted = pending_turn_state["other_participant_submitted"]
                        actions_by_role = pending_turn_state["actions_by_role"]
                    render_waiting_for_generation = False
                else:
                    log_turn_action_event(
                        "pending_turn_actions_claim_failed_from_render",
                        submit_trace_id=render_trace_id,
                        session_id=session_id,
                        turn_index=current_turn,
                        claim_status=claim_status
                    )
                    render_waiting_for_generation = True
                    pending_turn_state = load_pending_turn_state(
                        session_id=session_id,
                        turn_index=current_turn,
                        current_user_id=st.session_state.user_id
                    )
                    active_pending_actions = pending_turn_state["active_pending_actions"]
                    current_user_pending_action = pending_turn_state["current_user_pending_action"]
                    other_pending_action = pending_turn_state["other_pending_action"]
                    other_participant_submitted = pending_turn_state["other_participant_submitted"]
                    actions_by_role = pending_turn_state["actions_by_role"]
            except Exception as exc:
                if not has_completed_turn(session_id, current_turn):
                    reset_pending_turn_actions_to_pending(session_id, current_turn)
                log_turn_action_event(
                    "render_joint_turn_generation_exception",
                    submit_trace_id=render_trace_id,
                    exception_type=type(exc).__name__,
                    exception_message=str(exc),
                    source="render_joint_generation"
                )
                render_waiting_for_generation = True
                pending_turn_state = load_pending_turn_state(
                    session_id=session_id,
                    turn_index=current_turn,
                    current_user_id=st.session_state.user_id
                )
                active_pending_actions = pending_turn_state["active_pending_actions"]
                current_user_pending_action = pending_turn_state["current_user_pending_action"]
                other_pending_action = pending_turn_state["other_pending_action"]
                other_participant_submitted = pending_turn_state["other_participant_submitted"]
                actions_by_role = pending_turn_state["actions_by_role"]
                st.error("Something went wrong while processing the joint turn. Please try again.")

        should_poll_for_pending_turn = (
            (current_user_pending_action is not None and other_pending_action is None)
            or (current_user_pending_action is None and other_pending_action is not None)
            or (current_user_pending_action is not None and other_pending_action is not None)
            or (
                current_user_pending_action is not None
                and current_user_pending_action.get("status") == "generating"
            )
            or (
                other_pending_action is not None
                and other_pending_action.get("status") == "generating"
            )
            or render_waiting_for_generation
        )
        room_refresh_enabled = True
        if should_poll_for_pending_turn:
            room_refresh_interval_ms = ACTIVE_SESSION_PENDING_REFRESH_INTERVAL_MS
            room_refresh_reason = "pending_turn_wait_or_generation"
        else:
            room_refresh_interval_ms = ACTIVE_SESSION_IDLE_REFRESH_INTERVAL_MS
            room_refresh_reason = "active_session_sync"

        maybe_log_pending_turn_ui_status(
            session_id=session_id,
            turn_index=current_turn,
            current_user_pending_action=current_user_pending_action,
            other_pending_action=other_pending_action,
            pending_count=len(active_pending_actions),
            force=should_show_ai_coach_debug()
        )

        with right_col.container(border=True):
            st.subheader("Submit Turn Action")
            st.caption("Use one concrete action to push the shared story into the next turn.")
            if current_user_pending_action is not None:
                clear_turn_action_validation_feedback(
                    session_id=session_id,
                    turn_index=current_turn,
                    user_id=st.session_state.user_id
                )
            validation_feedback_container = st.empty()
            render_turn_action_validation_feedback(
                validation_feedback_container,
                session_id=session_id,
                turn_index=current_turn,
                user_id=st.session_state.user_id
            )

            with st.container(border=True):
                with st.form("turn_action_form", clear_on_submit=True):
                    action_input = st.text_area(
                        "What action do you want to take next?",
                        placeholder="例如：我会问他今晚能不能坐下来谈一谈。 / For example: I will ask if we can sit down tonight and talk honestly.",
                        disabled=current_user_pending_action is not None
                    )
                    action_submit = st.form_submit_button(
                        "Submit Action and Advance Turn",
                        disabled=current_user_pending_action is not None
                    )

                    if action_submit:
                        turn_action_trace_id = str(uuid.uuid4())[:8]
                        action_input_value = (action_input or "").strip()
                        submit_user_id = st.session_state.user_id
                        submit_room_id = st.session_state.room_id
                        log_turn_action_event(
                            "submit_turn_action_started",
                            submit_trace_id=turn_action_trace_id,
                            session_id=session_id,
                            turn_index=current_turn,
                            user_id=submit_user_id,
                            role_name=user_role,
                            action_length=len(action_input_value)
                        )

                        if action_input_value == "":
                            clear_turn_action_validation_feedback(
                                session_id=session_id,
                                turn_index=current_turn,
                                user_id=submit_user_id
                            )
                            st.error("Action cannot be empty.")
                        else:
                            recent_turn_history = get_turn_history(session_id)[-3:]
                            log_turn_action_event(
                                "submit_turn_action_local_validation_started",
                                submit_trace_id=turn_action_trace_id,
                                session_id=session_id,
                                turn_index=current_turn,
                                history_count=len(recent_turn_history)
                            )
                            validation = validate_turn_action(
                                action_text=action_input_value,
                                current_session=current_session,
                                user_role=user_role
                            )

                            if not validation["is_valid"]:
                                feedback_message = normalize_app_text(validation.get("feedback"))
                                log_turn_action_event(
                                    "submit_turn_action_local_validation_rejected",
                                    submit_trace_id=turn_action_trace_id,
                                    reason=short_debug_preview(feedback_message)
                                )
                                if feedback_message:
                                    set_turn_action_validation_feedback(
                                        session_id=session_id,
                                        turn_index=current_turn,
                                        user_id=submit_user_id,
                                        message=feedback_message
                                    )
                                else:
                                    set_turn_action_validation_feedback(
                                        session_id=session_id,
                                        turn_index=current_turn,
                                        user_id=submit_user_id,
                                        message="Your action needs to be more concrete before the scenario can advance."
                                    )
                                render_turn_action_validation_feedback(
                                    validation_feedback_container,
                                    session_id=session_id,
                                    turn_index=current_turn,
                                    user_id=submit_user_id,
                                    force=True
                                )
                            else:
                                log_turn_action_event(
                                    "submit_turn_action_local_validation_accepted",
                                    submit_trace_id=turn_action_trace_id
                                )
                                clear_turn_action_validation_feedback(
                                    session_id=session_id,
                                    turn_index=current_turn,
                                    user_id=submit_user_id
                                )
                                try:
                                    log_turn_action_event(
                                        "pending_turn_action_save_started",
                                        submit_trace_id=turn_action_trace_id,
                                        session_id=session_id,
                                        turn_index=current_turn,
                                        user_id=submit_user_id,
                                        role_name=user_role,
                                        action_length=len(action_input_value)
                                    )
                                    pending_action_id = save_pending_turn_action(
                                        session_id=session_id,
                                        turn_index=current_turn,
                                        user_id=submit_user_id,
                                        role_name=user_role,
                                        action_text=action_input_value
                                    )
                                    log_turn_action_event(
                                        "pending_turn_action_saved",
                                        submit_trace_id=turn_action_trace_id,
                                        pending_action_id=pending_action_id
                                    )
                                    bump_room_sync_event(
                                        room_id=submit_room_id,
                                        session_id=session_id,
                                        event_type="turn_action_submitted"
                                    )
                                    refreshed_pending_actions = get_pending_turn_actions_for_session_turn(
                                        session_id,
                                        current_turn
                                    )
                                    refreshed_actions_by_role = {
                                        action["role_name"]: action
                                        for action in refreshed_pending_actions
                                    }

                                    if has_completed_turn(session_id, current_turn):
                                        mark_pending_turn_actions_consumed(session_id, current_turn)
                                        log_turn_action_event(
                                            "joint_turn_already_completed_skip_generation",
                                            submit_trace_id=turn_action_trace_id,
                                            session_id=session_id,
                                            turn_index=current_turn
                                        )
                                        st.info("This turn already advanced. Reloading the latest scenario state.")
                                        st.rerun()

                                    if "role_a" not in refreshed_actions_by_role or "role_b" not in refreshed_actions_by_role:
                                        log_turn_action_event(
                                            "pending_turn_action_saved_waiting_for_other",
                                            submit_trace_id=turn_action_trace_id,
                                            session_id=session_id,
                                            turn_index=current_turn
                                        )
                                        st.success("Your action has been submitted. Waiting for the other participant.")
                                        st.rerun()

                                    log_turn_action_event(
                                        "pending_turn_actions_both_ready_after_save",
                                        submit_trace_id=turn_action_trace_id,
                                        session_id=session_id,
                                        turn_index=current_turn
                                    )
                                    claim_result = claim_pending_turn_actions_for_generation(
                                        session_id=session_id,
                                        turn_index=current_turn
                                    )
                                    claim_status = claim_result.get("status")

                                    if claim_status == "already_completed":
                                        mark_pending_turn_actions_consumed(session_id, current_turn)
                                        log_turn_action_event(
                                            "joint_turn_already_completed_skip_generation",
                                            submit_trace_id=turn_action_trace_id,
                                            session_id=session_id,
                                            turn_index=current_turn
                                        )
                                        st.info("This turn already advanced. Reloading the latest scenario state.")
                                        st.rerun()

                                    if claim_status != "ready":
                                        st.success("Your action has been submitted. Waiting for the other participant.")
                                        st.rerun()

                                    actions_by_role = claim_result.get("actions") or {}
                                    log_turn_action_event(
                                        "pending_turn_actions_both_ready",
                                        submit_trace_id=turn_action_trace_id,
                                        session_id=session_id,
                                        turn_index=current_turn
                                    )
                                    process_claimed_joint_turn(
                                        session_id=session_id,
                                        current_turn=current_turn,
                                        submit_room_id=submit_room_id,
                                        evolved_current_session=evolved_current_session,
                                        recent_turn_history=recent_turn_history,
                                        actions_by_role=actions_by_role,
                                        submit_trace_id=turn_action_trace_id,
                                        trigger_source="submit"
                                    )
                                except Exception as exc:
                                    if not has_completed_turn(session_id, current_turn):
                                        reset_pending_turn_actions_to_pending(session_id, current_turn)
                                    log_turn_action_event(
                                        "submit_turn_action_exception",
                                        submit_trace_id=turn_action_trace_id,
                                        exception_type=type(exc).__name__,
                                        exception_message=str(exc)
                                    )
                                    st.error("Something went wrong while processing the joint turn. Please try again.")

            with st.container(border=True):
                st.markdown("**Turn Submission Status**")
                st.write(
                    f"**You:** {'Submitted' if current_user_pending_action is not None else 'Not yet submitted'}"
                )
                st.write(
                    f"**Other participant:** {'Submitted' if other_participant_submitted else 'Waiting'}"
                )
                if current_user_pending_action is not None:
                    st.write(
                        f"**Your submitted action:** {normalize_app_text(current_user_pending_action.get('action_text'))}"
                    )
                if other_pending_action is not None:
                    st.write("**Other participant's action:**")
                    with st.container(border=True):
                        st.write(normalize_app_text(other_pending_action.get("action_text")))

            if current_user_pending_action is not None:
                maybe_log_pending_turn_wait_event(
                    "pending_turn_action_current_user_already_submitted",
                    signature=(
                        session_id,
                        current_turn,
                        "current_user_submitted",
                        current_user_pending_action.get("status"),
                        other_participant_submitted,
                    ),
                    session_id=session_id,
                    turn_index=current_turn,
                    status=current_user_pending_action.get("status"),
                    force=should_show_ai_coach_debug()
                )
                if (
                    current_user_pending_action.get("status") == "generating"
                    or render_waiting_for_generation
                ):
                    st.info("Waiting for story generation...")
                elif other_participant_submitted:
                    st.info("Your action has been submitted. Waiting for the story to advance.")
                else:
                    st.info("Your action has been submitted. Waiting for the other participant.")
            elif other_pending_action is not None:
                maybe_log_pending_turn_wait_event(
                    "pending_turn_action_other_action_visible",
                    signature=(
                        session_id,
                        current_turn,
                        "other_visible",
                        other_pending_action.get("role_name"),
                        short_debug_preview(other_pending_action.get("action_text")),
                    ),
                    session_id=session_id,
                    turn_index=current_turn,
                    other_role_name=other_pending_action.get("role_name"),
                    other_action_preview=short_debug_preview(other_pending_action.get("action_text")),
                    force=should_show_ai_coach_debug()
                )
                maybe_log_pending_turn_wait_event(
                    "pending_turn_action_current_user_can_respond",
                    signature=(
                        session_id,
                        current_turn,
                        "current_user_can_respond",
                        other_pending_action.get("role_name"),
                        other_pending_action.get("status"),
                    ),
                    session_id=session_id,
                    turn_index=current_turn,
                    other_role_name=other_pending_action.get("role_name"),
                    force=should_show_ai_coach_debug()
                )
                st.info("The other participant has already acted this turn:")
                with st.container(border=True):
                    st.write(normalize_app_text(other_pending_action.get("action_text")))
                st.caption("Now choose how your character responds.")

            st.caption("The story advances only after both participants submit valid actions for this turn.")

            if st.button("Reload Turn", key="active_reload_turn"):
                st.rerun()

    if current_session is not None:
        with right_col.container(border=True):
            st.subheader("Shared Role-play Chat")

            messages = get_messages_by_room(st.session_state.room_id)

            for msg in messages:
                msg_user_id = msg[0]
                msg_username = msg[1]
                msg_content = msg[2]
                msg_time = msg[3]

                if (msg_username or "").strip() != "":
                    st.write(f"**{msg_username}**: {msg_content}")
                else:
                    st.write(f"**{msg_user_id}**: {msg_content}")

            with st.form("shared_chat_form", clear_on_submit=True):
                new_message = st.text_input("Message to the other user")
                submitted = st.form_submit_button("Send Message")

                if submitted:
                    new_message_value = (new_message or "").strip()

                    if new_message_value == "":
                        st.error("Message cannot be empty.")
                    else:
                        add_message(
                            st.session_state.room_id,
                            st.session_state.user_id,
                            st.session_state.username,
                            new_message_value
                        )
                        bump_room_sync_event(
                            room_id=st.session_state.room_id,
                            session_id=session_id,
                            event_type="shared_chat_message_sent"
                        )
                        st.rerun()

    else:
        with waiting_right_col:
            with st.container(border=True):
                st.subheader("Shared Role-play Chat")

                messages = get_messages_by_room(st.session_state.room_id)

                for msg in messages:
                    msg_user_id = msg[0]
                    msg_username = msg[1]
                    msg_content = msg[2]
                    msg_time = msg[3]

                    if (msg_username or "").strip() != "":
                        st.write(f"**{msg_username}**: {msg_content}")
                    else:
                        st.write(f"**{msg_user_id}**: {msg_content}")

                with st.form("shared_chat_form", clear_on_submit=True):
                    new_message = st.text_input("Message to the other user")
                    submitted = st.form_submit_button("Send Message")

                    if submitted:
                        new_message_value = (new_message or "").strip()

                        if new_message_value == "":
                            st.error("Message cannot be empty.")
                        else:
                            add_message(
                                st.session_state.room_id,
                                st.session_state.user_id,
                                st.session_state.username,
                                new_message_value
                            )
                            bump_room_sync_event(
                                room_id=st.session_state.room_id,
                                event_type="shared_chat_message_sent"
                            )
                            st.rerun()

    if refresh_members_clicked:
        st.rerun()

    if leave_room_clicked:
        if st.session_state.user_id and st.session_state.room_id:
            departing_room_id = st.session_state.room_id
            remove_member(
                st.session_state.user_id,
                st.session_state.room_id
            )
            bump_room_sync_event(
                room_id=departing_room_id,
                session_id=current_session_id_for_sync,
                event_type="member_left"
            )
            clear_last_seen_room_event_version(departing_room_id)
        st.session_state.ai_coach_submit_in_progress = False
        st.session_state.ai_coach_force_reload = False
        st.session_state.ai_coach_force_reload_context = None
        st.session_state.last_ai_coach_debug = None
        st.session_state.sync_event_version_check_signature = None
        st.session_state.sync_polling_state_signature = None
        st.session_state.room_id = None
        st.session_state.invite_code = None
        clear_url()
        st.rerun()

    if st.session_state.ai_coach_submit_in_progress:
        maybe_log_sync_polling_state(
            enabled=False,
            reason="ai_coach_submit_in_progress",
            room_id=st.session_state.room_id,
            session_id=current_session_id_for_sync,
            force=should_show_ai_coach_debug()
        )
        log_ai_submit_event(
            "polling_disabled_for_ai_coach_submit",
            submit_trace_id=(st.session_state.get("last_ai_coach_debug") or {}).get("submit_trace_id"),
            pipeline_stage=(st.session_state.get("last_ai_coach_debug") or {}).get("pipeline_stage")
        )
    elif room_refresh_enabled:
        maybe_log_sync_polling_state(
            enabled=True,
            reason=room_refresh_reason,
            interval_ms=room_refresh_interval_ms,
            room_id=st.session_state.room_id,
            session_id=current_session_id_for_sync,
            force=should_show_ai_coach_debug()
        )
        st_autorefresh(interval=room_refresh_interval_ms, key="room_refresh")
    else:
        maybe_log_sync_polling_state(
            enabled=False,
            reason=room_refresh_reason,
            room_id=st.session_state.room_id,
            session_id=current_session_id_for_sync,
            force=should_show_ai_coach_debug()
        )

