from streamlit_autorefresh import st_autorefresh
import streamlit as st
import uuid
import random
import string
import json

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
    has_ai_prompt_for_stage,
    update_session_stage
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
        "stages": [
            {
                "stage_index": 1,
                "title": "Immediate Reflection",
                "goal": "Each side reflects on the conflict from their own perspective.",
                "prompt_a": "Looking back at the earlier interaction, what consequences might your expression have on management effectiveness and long-term team stability?",
                "prompt_b": "You feel the evaluation was unfair and the tone hurt you. How do you plan to handle your next action and communication?"
            },
            {
                "stage_index": 2,
                "title": "First Repair Attempt",
                "goal": "One side initiates follow-up action and the other side reacts.",
                "prompt_a": "You are considering sending a private apology message first. What exactly would you say, and what result do you want?",
                "prompt_b": "Your supervisor has sent an apology and proposed a follow-up conversation. What is your first reaction, and what do you want to clarify?"
            },
            {
                "stage_index": 3,
                "title": "Stabilizing the Relationship",
                "goal": "Both sides attempt to re-establish a clearer working relationship.",
                "prompt_a": "How would you explain your expectations more clearly next time without letting emotional noise take over?",
                "prompt_b": "What kind of communication boundary would help you feel respected while still keeping the conversation constructive?"
            }
        ]
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
    if current_session is None:
        return None

    stages = json.loads(current_session[7]) if current_session[7] else []
    current_stage_index = current_session[8]

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

    stages = json.loads(current_session[7]) if current_session[7] else []
    return len(stages)


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
                scenario["stages"]
            )

            members = get_members_by_room(st.session_state.room_id)

            if len(members) >= 1:
                assign_role(session_id, members[0][0], "role_a")

            if len(members) >= 2:
                assign_role(session_id, members[1][0], "role_b")

            st.rerun()

    else:
        session_id = current_session["id"]
        scenario_title = current_session["scenario_title"]
        scenario_context = current_session["scenario_context"]
        conflict = current_session["conflict"]
        role_a_brief = current_session["role_a_brief"]
        role_b_brief = current_session["role_b_brief"]
        current_stage_index = current_session["current_stage"]

        st.write("**Title:**", scenario_title)
        st.write("**Context:**", scenario_context)
        st.write("**Conflict:**", conflict)
        st.write("**Current Stage:**", current_stage_index)

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

        current_stage_obj = get_current_stage_obj(current_session)
        stage_prompt = get_stage_prompt_for_role(current_stage_obj, user_role)
        stage_count = get_stage_count(current_session)

        with st.expander("View Stage Framework"):
            stages = json.loads(current_session["stages_json"]) if current_session["stages_json"] else []
            current_stage_index = current_session["current_stage"]
            for stage in stages:
                st.markdown(f"### Stage {stage.get('stage_index')} - {stage.get('title', '')}")
                if stage.get("goal"):
                    st.write(f"**Goal:** {stage.get('goal')}")
                st.write(f"**Prompt A:** {stage.get('prompt_a', '')}")
                st.write(f"**Prompt B:** {stage.get('prompt_b', '')}")
                st.markdown("---")

        st.markdown("---")
        st.subheader("AI Coach Chat")

        # 第一次进入当前 stage 时，自动写入首条 AI prompt
        if user_role is not None and not has_ai_prompt_for_stage(
            session_id,
            current_stage_index,
            st.session_state.user_id
        ):
            if stage_prompt.strip():
                add_ai_message(
                    session_id=session_id,
                    stage_index=current_stage_index,
                    user_id=st.session_state.user_id,
                    role_name=user_role,
                    sender="ai",
                    content=stage_prompt
                )
                st.rerun()

        ai_messages = get_ai_messages(
            session_id=session_id,
            stage_index=current_stage_index,
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
                        stage_index=current_stage_index,
                        user_id=st.session_state.user_id,
                        role_name=user_role,
                        sender="user",
                        content=ai_input.strip()
                    )

                    ai_feedback = generate_fake_ai_feedback(
                        user_role=user_role,
                        user_text=ai_input.strip(),
                        stage_index=current_stage_index
                    )

                    add_ai_message(
                        session_id=session_id,
                        stage_index=current_stage_index,
                        user_id=st.session_state.user_id,
                        role_name=user_role,
                        sender="ai",
                        content=ai_feedback
                    )

                    st.rerun()

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Advance Scenario"):
                if current_stage_index < stage_count:
                    update_session_stage(session_id, current_stage_index + 1)
                    st.success(f"Scenario advanced to stage {current_stage_index + 1}")
                    st.rerun()
                else:
                    st.info("You are already at the final stage.")

        with col2:
            if st.button("Reload Stage"):
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