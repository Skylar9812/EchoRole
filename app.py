from streamlit_autorefresh import st_autorefresh
import streamlit as st
import uuid
import random
import string

from ai_engine import (
    build_turn_coach_prompt,
    generate_dynamic_ai_feedback,
    generate_next_situation,
    validate_turn_action
)

from database import (
    init_db,
    create_room,
    get_room_by_code,
    add_member,
    get_members_by_room,
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
    complete_turn
)

init_db()


# ---------- 1. 初始化 session_state ----------
if "user_id" not in st.session_state:
    st.session_state.user_id = None

if "username" not in st.session_state:
    st.session_state.username = ""

if "room_id" not in st.session_state:
    st.session_state.room_id = None

if "invite_code" not in st.session_state:
    st.session_state.invite_code = None


# ---------- 2. 从 URL 恢复用户身份 ----------
query_params = st.query_params

if st.session_state.user_id is None and "user_id" in query_params:
    st.session_state.user_id = query_params["user_id"]

if st.session_state.username == "" and "username" in query_params:
    st.session_state.username = query_params["username"]

if st.session_state.invite_code is None and "invite_code" in query_params:
    code_from_url = query_params["invite_code"]
    room = get_room_by_code(code_from_url)
    if room:
        st.session_state.invite_code = code_from_url
        st.session_state.room_id = room[0]


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


def ensure_user_created(username):
    """只有第一次才创建 user_id"""
    if st.session_state.user_id is None:
        st.session_state.user_id = str(uuid.uuid4())
    st.session_state.username = username
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

    st.subheader("Create a Room")
    if st.button("Create Room"):
        if username_input.strip() == "":
            st.error("Please enter a username first.")
        else:
            ensure_user_created(username_input.strip())

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
        if username_input.strip() == "":
            st.error("Please enter a username first.")
        else:
            room = get_room_by_code(input_code.strip())

            if room:
                ensure_user_created(username_input.strip())

                room_id = room[0]
                invite_code = room[1]

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
    st_autorefresh(interval=3000, key="room_refresh")

    st.success("You are in a room now!")

    st.write("Room code:")
    st.code(st.session_state.invite_code)

    st.write("Your username:")
    st.code(st.session_state.username)

    st.write("Your user ID:")
    st.code(st.session_state.user_id)

    st.subheader("Members in this room")
    members = get_members_by_room(st.session_state.room_id)

    for i, member in enumerate(members, start=1):
        user_id = member[0]
        nickname = member[1]

        if nickname and nickname.strip() != "":
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

            if "role_a" not in assigned_role_names:
                assign_role(session_id, st.session_state.user_id, "role_a")
            elif "role_b" not in assigned_role_names:
                assign_role(session_id, st.session_state.user_id, "role_b")

            st.rerun()

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
        turn_prompt = build_turn_coach_prompt(current_session, user_role)

        st.markdown("---")
        st.subheader("AI Coach Chat")

        # 第一次进入当前 stage 时，自动写入首条 AI prompt
        if user_role is not None and not has_ai_prompt_for_turn(
            session_id,
            current_turn,
            st.session_state.user_id
        ):
            if turn_prompt.strip():
                add_ai_message(
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

        if len(ai_messages) == 0:
            st.caption("No AI messages yet.")
        else:
            for msg in ai_messages:
                sender = msg[0]
                content = msg[1]
                created_at = msg[2]

                if sender == "ai":
                    st.info(f"AI: {content}")
                elif sender == "action":
                    st.caption(f"Your submitted action: {content}")
                else:
                    st.write(f"**You:** {content}")

        with st.form("ai_chat_form", clear_on_submit=True):
            ai_input = st.text_area("Reply to AI")
            ai_submit = st.form_submit_button("Send to AI")

            if ai_submit:
                if ai_input.strip() == "":
                    st.error("AI reply cannot be empty.")
                else:
                    add_ai_message(
                        session_id=session_id,
                        turn_index=current_turn,
                        user_id=st.session_state.user_id,
                        role_name=user_role,
                        sender="user",
                        content=ai_input.strip()
                    )

                    ai_feedback = generate_dynamic_ai_feedback(
                        user_role=user_role,
                        user_text=ai_input.strip(),
                        current_turn=current_turn,
                        current_situation=current_situation
                    )

                    add_ai_message(
                        session_id=session_id,
                        turn_index=current_turn,
                        user_id=st.session_state.user_id,
                        role_name=user_role,
                        sender="ai",
                        content=ai_feedback
                    )

                    st.rerun()

        st.subheader("Submit Turn Action")
        st.caption("Use one concrete action to push the shared story into the next turn.")

        with st.form("turn_action_form", clear_on_submit=True):
            action_input = st.text_area("What action do you want to take next?")
            action_submit = st.form_submit_button("Submit Action and Advance Turn")

            if action_submit:
                if action_input.strip() == "":
                    st.error("Action cannot be empty.")
                else:
                    validation = validate_turn_action(
                        action_text=action_input.strip(),
                        current_session=current_session,
                        user_role=user_role
                    )

                    if not validation["is_valid"]:
                        add_ai_message(
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
                        action_text=action_input.strip()
                    )

                    advanced = complete_turn(
                        session_id=session_id,
                        expected_turn=current_turn,
                        acting_user_id=st.session_state.user_id,
                        role_name=user_role,
                        submitted_action=action_input.strip(),
                        resulting_situation=next_situation
                    )

                    if advanced:
                        add_ai_message(
                            session_id=session_id,
                            turn_index=current_turn,
                            user_id=st.session_state.user_id,
                            role_name=user_role,
                            sender="action",
                            content=action_input.strip()
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

        if msg_username and msg_username.strip() != "":
            st.write(f"**{msg_username}**: {msg_content}")
        else:
            st.write(f"**{msg_user_id}**: {msg_content}")

    with st.form("shared_chat_form", clear_on_submit=True):
        new_message = st.text_input("Message to the other user")
        submitted = st.form_submit_button("Send Message")

        if submitted:
            if new_message.strip() == "":
                st.error("Message cannot be empty.")
            else:
                add_message(
                    st.session_state.room_id,
                    st.session_state.user_id,
                    st.session_state.username,
                    new_message.strip()
                )
                st.rerun()

    if st.button("Refresh Members"):
        st.rerun()

    if st.button("Leave Room"):
        st.session_state.room_id = None
        st.session_state.invite_code = None
        clear_url()
        st.rerun()
