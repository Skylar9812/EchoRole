from streamlit_autorefresh import st_autorefresh
import streamlit as st
import os
import uuid
import random
import string
from datetime import datetime

from ai_engine import (
    build_turn_coach_prompt,
    generate_dynamic_ai_feedback,
    get_last_ai_debug_info,
    generate_next_situation,
    validate_turn_action
)

from database import (
    init_db,
    create_room,
    get_room_by_code,
    add_member,
    remove_member,
    get_members_by_room,
    can_user_join_room,
    get_user_profile,
    save_user_profile,
    add_message,
    get_messages_by_room,
    create_session,
    get_session_by_room,
    assign_role,
    get_user_role,
    get_all_roles_in_session,
    add_ai_message,
    get_ai_messages,
    has_ai_prompt_for_turn,
    get_turn_history,
    complete_turn
)

init_db()

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


def render_ai_coach_messages(message_container, ai_messages, submit_trace_id=None):
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
        log_render_event("render_ai_coach_messages_before_container_context")
        with message_container.container():
            if len(ai_messages) == 0:
                log_render_event(
                    "render_ai_coach_messages_before_loop",
                    message_count=0
                )
                st.caption("No AI messages yet.")
                log_render_event(
                    "render_ai_coach_messages_after_loop",
                    rendered_message_count=0
                )
            else:
                log_render_event(
                    "render_ai_coach_messages_before_loop",
                    message_count=len(ai_messages)
                )
                for index, msg in enumerate(ai_messages):
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
                    rendered_message_count=len(ai_messages)
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


# ---------- 1. 初始化 session_state ----------
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


# ---------- 2. 从 URL 恢复用户身份 ----------
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
            add_member(
                st.session_state.user_id,
                room_id_from_url,
                st.session_state.username
            )
            st.session_state.invite_code = code_from_url
            st.session_state.room_id = room_id_from_url


def save_user_to_url():
    """把当前用户身份和房间信息写到 URL，刷新后还能保留"""
    if st.session_state.user_id:
        st.query_params["user_id"] = st.session_state.user_id
    if st.session_state.username:
        st.query_params["username"] = st.session_state.username
    if st.session_state.invite_code:
        st.query_params["invite_code"] = st.session_state.invite_code


def clear_url():
    """离开房间时清空 URL 参数"""
    st.query_params.clear()


def generate_invite_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_demo_scenario():
    return {
        "title": "Team Deadline Conflict",
        "context": "A product launch is approaching, and the team is under pressure.",
        "conflict": "The manager thinks the team member is not responsive enough. The team member feels overloaded and unsupported.",
        "role_a_brief": "You are the manager. You are worried the delay will affect the client relationship.",
        "role_b_brief": "You are the team member. You believe expectations are unrealistic and communication has been one-sided.",
        "opening_situation": (
            "In a team check-in, the delayed launch timeline becomes impossible to ignore. "
            "The manager raises concerns about responsiveness, while the team member feels cornered and unsupported. "
            "Both people leave the exchange tense and uncertain about what should happen next."
        )
    }


def ensure_user_created(username, mbti=None, priorities=None):
    """只有第一次才创建 user_id"""
    if st.session_state.user_id is None:
        st.session_state.user_id = str(uuid.uuid4())
    st.session_state.username = username
    save_user_profile(
        st.session_state.user_id,
        display_name=username,
        mbti=mbti,
        priorities=priorities
    )
    save_user_to_url()


def get_current_stage_obj(current_session):
    """
    current_session 是 database.py 里 get_session_by_room() 返回的 tuple:
    [0]=id, [1]=room_id, [2]=scenario_title, [3]=scenario_context, [4]=conflict,
    [5]=role_a_brief, [6]=role_b_brief, [7]=stages_json, [8]=current_stage, [9]=created_at
    """
    # current_session uses the dictionary shape returned by database.get_session_by_room().
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
    这里先用假反馈，后面你可以替换成真正的 LLM / RAG 版本
    """
    if user_role == "role_a":
        if stage_index == 1:
            return (
                "我理解你的判断逻辑。你现在把“压力训练”“标准传达”和“情绪表达”混在了一起。"
                "从训练角度，建议你先区分：你真正想达成的是管理效果，还是即时情绪释放？"
                "请继续说明：如果目标是长期团队稳定，你觉得你刚才的表达会带来哪些副作用？"
            )
        elif stage_index == 2:
            return (
                "你的重点不只是道歉本身，而是恢复对方对你判断系统的信任。"
                "请继续说明：你的道歉里，哪些内容是修复情绪体验，哪些内容是重新建立清晰标准？"
            )
        elif stage_index == 3:
            return (
                "现在重点已经从补救转向稳定关系。"
                "请继续说明：下次你会如何在前 30 秒内控制情绪噪声，同时把标准表达清楚？"
            )
        else:
            return "请继续展开你的判断。"

    elif user_role == "role_b":
        if stage_index == 1:
            return (
                "你已经表达出了受伤感和不公平感。下一步要把情绪判断和沟通策略拆开。"
                "请继续说明：如果你希望被认真对待而不是升级冲突，你最想先澄清什么事实？"
            )
        elif stage_index == 2:
            return (
                "对方的道歉可能缓和情绪，但未必已经解决问题。"
                "请继续说明：你最需要对方说清楚的是评价依据、沟通方式，还是之后的合作边界？"
            )
        elif stage_index == 3:
            return (
                "边界不是一次强烈表态，而是持续一致的回应模式。"
                "请继续说明：你希望用什么方式让对方知道，压迫式表达对你不起作用，但你仍愿意合作？"
            )
        else:
            return "请继续说明你的想法。"

    return "请继续展开你的想法。"


def get_stage_count(current_session):
    if current_session is None:
        return 0

    return len(current_session.get("stages", []))


st.title("EchoRole")


# ---------- 3. 大厅页 ----------
if st.session_state.room_id is None:
    st.write("Welcome to EchoRole!")

    username_input = st.text_input(
        "Enter your username",
        value=st.session_state.username
    )

    existing_profile = get_user_profile(st.session_state.user_id)
    mbti_input = st.text_input(
        "MBTI (optional)",
        value=existing_profile.get("mbti", "")
    )
    priorities_input = st.text_area(
        "Communication / value priorities (optional)",
        value=existing_profile.get("priorities", "")
    )

    st.subheader("Create a Room")
    if st.button("Create Room"):
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

            code = generate_invite_code()
            room_id = create_room(code)

            add_member(
                st.session_state.user_id,
                room_id,
                st.session_state.username
            )

            st.session_state.room_id = room_id
            st.session_state.invite_code = code
            save_user_to_url()
            st.rerun()

    st.subheader("Join a Room")
    input_code = st.text_input("Enter invite code")

    if st.button("Join Room"):
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
                    add_member(
                        st.session_state.user_id,
                        room_id,
                        st.session_state.username
                    )

                    st.session_state.room_id = room_id
                    st.session_state.invite_code = invite_code
                    save_user_to_url()
                    st.rerun()
            else:
                st.error("Invalid invite code")

# ---------- 4. 房间页 ----------
else:
    st.success("You are in a room now!")

    st.write("Room code:")
    st.code(st.session_state.invite_code)

    st.write("Your username:")
    st.code(st.session_state.username)

    st.write("Your user ID:")
    st.code(st.session_state.user_id)

    user_profile = get_user_profile(st.session_state.user_id)

    with st.expander("Your Profile"):
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
                    save_user_to_url()
                    st.success("Profile saved.")
                    st.rerun()

    st.subheader("Members in this room")
    members = get_members_by_room(st.session_state.room_id)

    for i, member in enumerate(members, start=1):
        user_id = member[0]
        nickname = member[1]

        if (nickname or "").strip() != "":
            st.write(f"Member {i}: {nickname}")
        else:
            st.write(f"Member {i}: {user_id}")

    st.markdown("---")
    st.subheader("Scenario")

    current_session = get_session_by_room(st.session_state.room_id)

    if current_session is None:
        if st.button("Generate Demo Scenario"):
            scenario = generate_demo_scenario()

            session_id = create_session(
                st.session_state.room_id,
                scenario["title"],
                scenario["context"],
                scenario["conflict"],
                scenario["role_a_brief"],
                scenario["role_b_brief"],
                scenario["opening_situation"]
            )

            members = get_members_by_room(st.session_state.room_id)

            if len(members) >= 1:
                assign_role(session_id, members[0][0], "role_a")

            if len(members) >= 2:
                assign_role(session_id, members[1][0], "role_b")

            st.rerun()

    else:
        session_id = current_session["id"]
        scenario_title = current_session["title"]
        scenario_context = current_session["context"]
        conflict = current_session["conflict"]
        role_a_brief = current_session["role_a_brief"]
        role_b_brief = current_session["role_b_brief"]
        current_turn = current_session["current_turn"]
        current_situation = current_session["current_situation"]

        st.write("**Title:**", scenario_title)
        st.write("**Context:**", scenario_context)
        st.write("**Conflict:**", conflict)
        st.write("**Current Turn:**", current_turn)
        st.write("**Current Situation:**", current_situation)

        user_role = get_user_role(session_id, st.session_state.user_id)

        if user_role is None:
            all_roles = get_all_roles_in_session(session_id)
            assigned_role_names = [row[1] for row in all_roles]
            role_assigned = False

            if "role_a" not in assigned_role_names:
                assign_role(session_id, st.session_state.user_id, "role_a")
                role_assigned = True
            elif "role_b" not in assigned_role_names:
                assign_role(session_id, st.session_state.user_id, "role_b")
                role_assigned = True

            if role_assigned:
                st.rerun()

            st.error("This active session already has two assigned participants.")
            st.stop()

        user_role = get_user_role(session_id, st.session_state.user_id)

        st.subheader("Your Role Brief")
        if user_role == "role_a":
            st.info(role_a_brief)
            st.write("Your role: A")
        elif user_role == "role_b":
            st.info(role_b_brief)
            st.write("Your role: B")
        else:
            st.warning("Your role has not been assigned yet.")

        recent_turn_history = get_turn_history(session_id)[-3:]
        turn_prompt = build_turn_coach_prompt(
            current_session,
            user_role,
            user_profile=user_profile,
            recent_turn_history=recent_turn_history
        )

        st.markdown("---")
        st.subheader("AI Coach Chat")

        # 第一次进入当前 stage 时，自动写入首条 AI prompt
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
        ai_messages_container = st.empty()
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
            )
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
            with st.expander("Coach Reply Debug", expanded=False):
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

        with st.form("ai_chat_form", clear_on_submit=True):
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
                            thinking_status = st.empty()
                            thinking_status.caption("AI Coach is thinking...")
                            log_ai_submit_event(
                                "after_entering_spinner",
                                submit_trace_id=submit_trace_id
                            )
                            log_ai_submit_event(
                                "before_generate_dynamic_ai_feedback_call",
                                submit_trace_id=submit_trace_id
                            )
                            ai_feedback = generate_dynamic_ai_feedback(
                                user_role=user_role,
                                user_text=ai_input_value,
                                current_turn=current_turn,
                                current_situation=current_situation,
                                user_profile=user_profile,
                                recent_turn_history=recent_turn_history,
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

        st.subheader("Submit Turn Action")
        st.caption("Use one concrete action to push the shared story into the next turn.")

        with st.form("turn_action_form", clear_on_submit=True):
            action_input = st.text_area("What action do you want to take next?")
            action_submit = st.form_submit_button("Submit Action and Advance Turn")

            if action_submit:
                action_input_value = (action_input or "").strip()

                if action_input_value == "":
                    st.error("Action cannot be empty.")
                else:
                    validation = validate_turn_action(
                        action_text=action_input_value,
                        current_session=current_session,
                        user_role=user_role
                    )

                    if not validation["is_valid"]:
                        add_ai_message_with_logging(
                            branch_name="validation_feedback_save",
                            session_id=session_id,
                            turn_index=current_turn,
                            user_id=st.session_state.user_id,
                            role_name=user_role,
                            sender="ai",
                            content=validation["feedback"]
                        )
                        st.warning("Revise the action before advancing the turn.")
                        st.rerun()

                    next_situation = generate_next_situation(
                        current_session=current_session,
                        user_role=user_role,
                        action_text=action_input_value
                    )

                    advanced = complete_turn(
                        session_id=session_id,
                        expected_turn=current_turn,
                        acting_user_id=st.session_state.user_id,
                        role_name=user_role,
                        submitted_action=action_input_value,
                        resulting_situation=next_situation
                    )

                    if advanced:
                        add_ai_message(
                            session_id=session_id,
                            turn_index=current_turn,
                            user_id=st.session_state.user_id,
                            role_name=user_role,
                            sender="action",
                            content=action_input_value
                        )
                        st.success(f"Story advanced to turn {current_turn + 1}")
                        st.rerun()
                    else:
                        st.warning("This turn was already advanced elsewhere. Reload to see the latest situation.")

        if st.button("Reload Turn"):
            st.rerun()

    st.markdown("---")
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
                st.rerun()

    if st.button("Refresh Members"):
        st.rerun()

    if st.button("Leave Room"):
        if st.session_state.user_id and st.session_state.room_id:
            remove_member(
                st.session_state.user_id,
                st.session_state.room_id
            )
        st.session_state.ai_coach_submit_in_progress = False
        st.session_state.ai_coach_force_reload = False
        st.session_state.ai_coach_force_reload_context = None
        st.session_state.last_ai_coach_debug = None
        st.session_state.room_id = None
        st.session_state.invite_code = None
        clear_url()
        st.rerun()

    if not st.session_state.ai_coach_submit_in_progress:
        st_autorefresh(interval=3000, key="room_refresh")
    else:
        log_ai_submit_event(
            "polling_disabled_for_ai_coach_submit",
            submit_trace_id=(st.session_state.get("last_ai_coach_debug") or {}).get("submit_trace_id"),
            pipeline_stage=(st.session_state.get("last_ai_coach_debug") or {}).get("pipeline_stage")
        )
