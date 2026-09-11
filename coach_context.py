"""Legacy text normalization and private Coach history filtering shared by both UIs."""

def normalize_app_text(value):
    if value is None:
        return ""

    if isinstance(value, bytes):
        normalized = value.decode("utf-8", errors="replace")
    else:
        normalized = str(value)

    normalized = normalized.replace("\x00", "")
    return normalized


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

    if limit <= 0:
        return visible_messages

    return visible_messages[-limit:]
