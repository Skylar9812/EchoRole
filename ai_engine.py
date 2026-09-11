"""Replaceable AI engine boundary for EchoRole.

Today's default behavior stays local and deterministic. A small provider and
config layer sits underneath the public helper functions so a future real LLM
provider can be plugged in without changing app.py.
"""

import json
from provider_boundary import mark_uncertain
import http.client
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import socket
import time
from typing import Any, Dict, List, Optional
from urllib import error
from urllib.parse import urlsplit
from rag_engine import retrieve_relevant_notes

_last_ai_debug_info: Dict[str, Any] = {}


def get_role_brief(current_session, user_role):
    if user_role == "role_a":
        return current_session.get("role_a_brief", "")
    if user_role == "role_b":
        return current_session.get("role_b_brief", "")
    return ""


def get_other_role(user_role):
    if user_role == "role_a":
        return "role_b"
    if user_role == "role_b":
        return "role_a"
    return ""


def get_other_role_brief(current_session, user_role):
    return get_role_brief(current_session, get_other_role(user_role))


def get_role_brief_history_entries(current_session, user_role):
    if user_role == "role_a":
        raw_entries = current_session.get("role_a_brief_history_entries") or []
    elif user_role == "role_b":
        raw_entries = current_session.get("role_b_brief_history_entries") or []
    else:
        raw_entries = []

    normalized_entries = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        brief_text = str(entry.get("brief_text") or "").strip()
        if brief_text == "":
            continue
        normalized_entries.append(
            {
                "turn_number": int(entry.get("turn_number", 0) or 0),
                "brief_text": brief_text,
            }
        )
    return normalized_entries


def format_role_brief_history_for_prompt(current_session, user_role, max_recent_turns=2):
    entries = get_role_brief_history_entries(current_session, user_role)
    if not entries:
        return ""

    selected_entries = []
    seen_turn_numbers = set()

    first_entry = entries[0]
    selected_entries.append(first_entry)
    seen_turn_numbers.add(first_entry["turn_number"])

    for entry in entries[-max_recent_turns:]:
        turn_number = entry["turn_number"]
        if turn_number in seen_turn_numbers:
            continue
        selected_entries.append(entry)
        seen_turn_numbers.add(turn_number)

    selected_entries.sort(key=lambda item: item["turn_number"])
    history_lines = [
        f"Turn {entry['turn_number']}: {entry['brief_text']}"
        for entry in selected_entries
    ]
    return "\n".join(history_lines)


def get_role_label(user_role):
    if user_role == "role_a":
        return "the manager"
    if user_role == "role_b":
        return "the team member"
    return "your role"


def format_user_profile_context(user_profile):
    if not user_profile:
        return ""

    parts = []
    preferred_order = ["display_name", "mbti", "priorities"]
    handled_keys = set()

    for key in preferred_order:
        value = str(user_profile.get(key, "") or "").strip()
        handled_keys.add(key)
        if value == "":
            continue
        if key == "display_name":
            parts.append(f"display name: {value}")
        elif key == "mbti":
            parts.append(f"MBTI: {value}")
        elif key == "priorities":
            parts.append(f"profile notes: {value}")

    for key, value in user_profile.items():
        if key in handled_keys or key in {"user_id", "updated_at"}:
            continue
        normalized_value = str(value or "").strip()
        if normalized_value:
            parts.append(f"{key}: {normalized_value}")

    if not parts:
        return ""

    return "; ".join(parts)


def format_recent_turn_history(recent_turn_history):
    if not recent_turn_history:
        return ""

    history_lines = []
    for turn in recent_turn_history:
        turn_index = turn.get("turn_index", "?")
        role_name = turn.get("role_name", "unknown role")
        action = turn.get("submitted_action", "")
        result = turn.get("resulting_situation", "")
        history_lines.append(
            f"Turn {turn_index} by {role_name}: action={action}; result={result}"
        )

    return "\n".join(history_lines)


def format_recent_shared_chat_history(recent_shared_chat):
    if not recent_shared_chat:
        return ""

    chat_lines = []
    for message in recent_shared_chat:
        if isinstance(message, dict):
            speaker = str(
                message.get("speaker")
                or message.get("username")
                or message.get("user_id")
                or "Participant"
            ).strip()
            content = str(message.get("content") or "").strip()
        elif isinstance(message, (list, tuple)) and len(message) >= 3:
            speaker = str(message[1] or message[0] or "Participant").strip()
            content = str(message[2] or "").strip()
        else:
            continue

        if content == "":
            continue
        chat_lines.append(f"{speaker}: {content}")

    return "\n".join(chat_lines)


def format_messages_as_prompt_text(messages):
    if not messages:
        return ""

    blocks = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "message").strip().upper()
        content = str(message.get("content") or "").strip()
        if content == "":
            continue
        blocks.append(f"[{role}]\n{content}")
    return "\n\n".join(blocks).strip()


def format_recent_coach_history(recent_coach_history):
    if not recent_coach_history:
        return ""

    history_lines = []
    for message in recent_coach_history:
        sender = str(message.get("sender") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if content == "":
            continue

        if sender == "ai":
            speaker = "Coach"
        elif sender == "user":
            speaker = "User"
        else:
            speaker = sender or "Message"

        turn_index = message.get("turn_index", "?")
        history_lines.append(
            f"Turn {turn_index} {speaker}: {content}"
        )

    return "\n".join(history_lines)


def infer_latest_user_message_language(user_text):
    text = str(user_text or "").strip()
    if text == "":
        return "mixed"

    chinese_char_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_letter_count = len(re.findall(r"[A-Za-z]", text))

    if chinese_char_count > english_letter_count:
        return "zh"
    if english_letter_count > chinese_char_count:
        return "en"

    return "mixed"


def describe_latest_user_message_language(language_code):
    if language_code == "zh":
        return "Chinese"
    if language_code == "en":
        return "English"
    return "Mixed; reply in the dominant language of the latest user message."


def count_prior_visible_user_messages(recent_coach_history):
    if not recent_coach_history:
        return 0

    visible_user_message_count = 0
    for message in recent_coach_history:
        sender = str(message.get("sender") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if sender == "user" and content != "":
            visible_user_message_count += 1

    return visible_user_message_count


def format_rag_notes_for_prompt(rag_notes):
    if not rag_notes:
        return "No relevant local guidance notes retrieved."

    note_blocks = []
    for index, note in enumerate(rag_notes, start=1):
        title = str(note.get("title") or f"Note {index}").strip()
        category = str(note.get("category") or "").strip()
        preview = str(note.get("preview") or "").strip()
        if len(preview) > 700:
            preview = preview[:697] + "..."

        prefix = f"Note {index}: {title}"
        if category:
            prefix += f" [{category}]"

        note_blocks.append(f"{prefix}\n{preview}")

    return "\n\n".join(note_blocks)


def build_coach_rag_query(
    *,
    current_session,
    user_role,
    user_text,
    user_profile=None,
    recent_turn_history=None
):
    recent_history_context = format_recent_turn_history(recent_turn_history)
    profile_context = format_user_profile_context(user_profile)
    return "\n".join([
        str(current_session.get("title", "") or ""),
        str(current_session.get("context", "") or ""),
        str(current_session.get("conflict", "") or ""),
        str(current_session.get("current_situation", "") or ""),
        str(get_role_brief(current_session, user_role) or ""),
        str(user_text or ""),
        profile_context,
        recent_history_context,
    ]).strip()


def _short_debug_text(text, limit=180):
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _is_truthy_env_flag(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _set_last_ai_debug_info(**kwargs):
    global _last_ai_debug_info
    _last_ai_debug_info = dict(kwargs)


def get_last_ai_debug_info():
    return dict(_last_ai_debug_info)


def _log_provider_event(event, debug_trace_id=None, **fields):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trace_label = debug_trace_id or "-"
    field_parts = []
    for key, value in fields.items():
        if value is None:
            continue
        field_parts.append(f"{key}={value!r}")

    suffix = ""
    if field_parts:
        suffix = " " + " ".join(field_parts)

    print(
        f"[EchoRole][AIProvider][{timestamp}] trace={trace_label} event={event}{suffix}",
        flush=True
    )


@dataclass(frozen=True)
class AIEngineConfig:
    provider_name: str = ""
    provider_env_present: bool = False
    llm_api_key: str = ""
    llm_api_key_source: str = "none"
    llm_model: str = ""
    llm_api_base: str = ""
    llm_timeout_seconds: float = 12.0

    @classmethod
    def from_env(cls):
        provider_env_raw = os.getenv("ECHOROLE_AI_PROVIDER")
        explicit_provider_name = (provider_env_raw or "").strip()
        primary_llm_api_key = (os.getenv("ECHOROLE_LLM_API_KEY", "") or "").strip()
        deepseek_api_key = (os.getenv("DEEPSEEK_API_KEY", "") or "").strip()

        llm_api_key = ""
        llm_api_key_source = "none"
        if primary_llm_api_key:
            llm_api_key = primary_llm_api_key
            llm_api_key_source = "ECHOROLE_LLM_API_KEY"
        elif deepseek_api_key:
            llm_api_key = deepseek_api_key
            llm_api_key_source = "DEEPSEEK_API_KEY"

        return cls(
            provider_name=explicit_provider_name,
            provider_env_present=explicit_provider_name != "",
            llm_api_key=llm_api_key,
            llm_api_key_source=llm_api_key_source,
            llm_model=os.getenv("ECHOROLE_LLM_MODEL", ""),
            llm_api_base=os.getenv("ECHOROLE_LLM_API_BASE", "")
        )

    def resolved_provider_name(self):
        if self.provider_env_present:
            explicit_provider_name = (self.provider_name or "").strip().lower()
            if explicit_provider_name:
                return explicit_provider_name

        if self.resolved_llm_api_key() != "":
            return "llm"

        return "local"

    def provider_selection_reason(self):
        if self.provider_env_present:
            return "explicit_provider_env"
        if self.resolved_llm_api_key() != "":
            return "auto_llm_key_present"
        return "auto_no_llm_key"

    def resolved_llm_api_key(self):
        return (self.llm_api_key or "").strip()

    def resolved_llm_api_key_source(self):
        if self.resolved_llm_api_key() == "":
            return "none"
        return (self.llm_api_key_source or "unknown").strip() or "unknown"

    def has_llm_api_key(self):
        return self.resolved_llm_api_key() != ""

    def resolved_llm_model(self):
        model = (self.llm_model or "").strip()
        if model == "":
            return "deepseek-v4-flash"
        return model

    def resolved_llm_api_base(self):
        api_base = (self.llm_api_base or "").strip()
        if api_base == "":
            api_base = "https://api.deepseek.com"
        return api_base.rstrip("/")

    def resolved_llm_timeout_seconds(self):
        if self.llm_timeout_seconds <= 0:
            return 12.0
        return float(self.llm_timeout_seconds)


class AIProvider:
    def build_turn_coach_prompt(
        self,
        current_session,
        user_role,
        user_profile=None,
        recent_turn_history=None
    ):
        raise NotImplementedError

    def validate_turn_action(self, action_text, current_session, user_role):
        raise NotImplementedError

    def evaluate_turn_action(
        self,
        action_text,
        current_session,
        user_role,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        raise NotImplementedError

    def generate_dynamic_ai_feedback(
        self,
        user_role,
        user_text,
        current_turn,
        current_situation,
        current_session=None,
        user_profile=None,
        recent_turn_history=None,
        recent_coach_history=None,
        debug_trace_id=None
    ):
        raise NotImplementedError

    def generate_next_situation(
        self,
        current_session,
        user_role,
        action_text,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        raise NotImplementedError

    def generate_next_situation_from_joint_actions(
        self,
        current_session,
        role_a_action,
        role_b_action,
        recent_turn_history=None,
        recent_shared_chat=None,
        debug_trace_id=None
    ):
        raise NotImplementedError


def _build_provider_selection_debug_fields(config: AIEngineConfig):
    requested_provider_name = config.resolved_provider_name()
    if requested_provider_name == "deepseek":
        requested_provider_name = "llm"
    provider_selected = (
        requested_provider_name
        if requested_provider_name in _provider_registry
        else "local"
    )
    selection_reason = config.provider_selection_reason()
    if provider_selected != requested_provider_name:
        selection_reason = f"{selection_reason}_unknown_fallback_local"

    return {
        "provider_selected": provider_selected,
        "provider_selection_reason": selection_reason,
        "provider_env_present": bool(config.provider_env_present),
        "echorole_ai_provider_explicit": bool(config.provider_env_present),
        "llm_api_key_present": config.has_llm_api_key(),
        "api_key_present": config.has_llm_api_key(),
        "llm_api_key_source": config.resolved_llm_api_key_source(),
    }


def _build_turn_coach_prompt_local(
    current_session,
    user_role,
    user_profile=None,
    recent_turn_history=None
):
    role_brief = get_role_brief(current_session, user_role)
    if role_brief.strip() == "":
        return ""

    profile_context = format_user_profile_context(user_profile)
    recent_history_context = format_recent_turn_history(recent_turn_history)

    profile_section = ""
    if profile_context:
        profile_section = f"Your profile context: {profile_context}\n\n"

    role_brief_history_context = format_role_brief_history_for_prompt(
        current_session,
        user_role,
        max_recent_turns=2
    )
    role_brief_history_section = ""
    if role_brief_history_context:
        role_brief_history_section = (
            f"Relevant private role brief history:\n{role_brief_history_context}\n\n"
        )

    history_section = ""
    if recent_history_context:
        history_section = f"Recent progression history:\n{recent_history_context}\n\n"

    return (
        f"Turn {current_session['current_turn']}\n\n"
        f"Current situation: {current_session['current_situation']}\n\n"
        f"Your private role brief: {role_brief}\n\n"
        f"{profile_section}"
        f"{role_brief_history_section}"
        f"{history_section}"
        "Reflect on what matters most to you right now, what risk you see in the situation, "
        "and what move you are considering next. Reply naturally and the coach will help you think it through."
    )


def classify_action_signal(text):
    lowered = text.lower()

    if any(keyword in lowered for keyword in ["apolog", "sorry", "repair", "listen", "understand", "acknowledge"]):
        return "repair"
    if any(keyword in lowered for keyword in ["ask", "clarify", "question", "discuss", "meet", "explain"]):
        return "clarify"
    if any(keyword in lowered for keyword in ["demand", "insist", "fault", "blame", "must", "warn"]):
        return "escalate"
    return "explore"


def _classify_story_progression_action_signal(text):
    lowered = str(text or "").strip().lower()
    if lowered == "":
        return "explore"

    repair_markers = [
        "agree", "apolog", "forgive", "listen", "make up", "plan", "promise",
        "repair", "support", "travel", "trip", "understand", "work it out",
        "\u540c\u610f", "\u539f\u8c05", "\u548c\u597d", "\u5b89\u6392",
        "\u65c5\u884c", "\u8865\u8fc7", "\u8ba1\u5212", "\u7b54\u5e94",
        "\u7406\u89e3", "\u652f\u6301",
    ]
    clarify_markers = [
        "ask", "check in", "clarify", "discuss", "explain", "follow up", "meet",
        "question", "schedule", "talk",
        "\u6253\u7535\u8bdd", "\u53d1\u6d88\u606f", "\u53d1\u4fe1\u606f",
        "\u8ba8\u8bba", "\u6c9f\u901a", "\u89e3\u91ca", "\u8be2\u95ee",
        "\u95ee", "\u7ea6", "\u7ea6\u65f6\u95f4", "\u8c08\u4e00\u8c08",
        "\u804a\u4e00\u804a",
    ]
    escalate_markers = [
        "blame", "demand", "fault", "insist", "threat", "warn",
        "\u6307\u8d23", "\u5a01\u80c1", "\u903c", "\u602a\u7f6a", "\u65bd\u538b",
    ]

    if any(marker in lowered for marker in repair_markers):
        return "repair"
    if any(marker in lowered for marker in clarify_markers):
        return "clarify"
    if any(marker in lowered for marker in escalate_markers):
        return "escalate"
    return classify_action_signal(text)


TURN_ACTION_SOCIAL_PREFIXES = [
    "accept", "acknowledg", "admit", "apolog", "ask", "call", "check",
    "clarif", "comfort", "confront", "discuss", "explain", "follow",
    "invit", "join", "leave", "listen", "meet", "message", "messag",
    "negotiat", "offer", "pause", "propos", "refus", "reassur",
    "request", "respond", "restart", "say", "schedul", "set", "share",
    "sit", "suggest", "support", "talk", "tell", "text", "understand",
    "wait", "walk",
]

TURN_ACTION_SOCIAL_PHRASES = [
    "check in", "follow up", "give space", "have coffee", "make peace",
    "sit down", "start over", "take a walk",
]

TURN_ACTION_SOCIAL_MARKERS_ZH = [
    "说", "告诉", "问", "询问", "建议", "提议", "解释", "表达", "道歉",
    "接受", "拒绝", "同意", "请求", "邀请", "澄清", "讨论", "沟通",
    "打电话", "发消息", "发信息", "约时间", "约他", "约她", "约对方",
]

TURN_ACTION_COUNTERPART_TERMS = [
    "boss", "child", "client", "colleague", "coworker", "co-worker",
    "daughter", "employee", "father", "friend", "he", "her", "him",
    "manager", "member", "mother", "our", "parent", "partner", "roommate",
    "son", "student", "supervisor", "teammate", "teammate", "teacher",
    "them", "their", "wife", "husband", "girlfriend", "boyfriend",
]

TURN_ACTION_COUNTERPART_TERMS_ZH = [
    "他", "她", "他们", "她们", "对方", "伴侣", "朋友", "同事", "队友",
    "经理", "员工", "父母", "爸爸", "妈妈", "孩子", "老师", "学生",
]

TURN_ACTION_EMOTION_KEYWORDS = [
    "angry", "anxious", "annoyed", "ashamed", "disappointed", "frustrated",
    "hurt", "mad", "nervous", "overwhelmed", "sad", "stressed", "upset",
    "worried",
]

TURN_ACTION_EMOTION_KEYWORDS_ZH = [
    "难过", "伤心", "生气", "愤怒", "焦虑", "不安", "委屈", "害怕",
    "紧张", "失望", "难受", "烦", "痛苦",
]

TURN_ACTION_VAGUE_PHRASES = [
    "do better", "do something", "fix it", "handle it", "be nice",
    "be better", "calm down", "try harder", "make it work", "say something",
    "deal with it", "figure it out",
]

TURN_ACTION_VAGUE_PHRASES_ZH = [
    "做点什么", "做些什么", "处理一下", "想办法", "解决一下",
    "我会沟通一下", "我会说一下", "我会聊聊", "我会谈谈", "我会问问",
]

TURN_ACTION_META_PHRASES = [
    "advance the story", "advance turn", "ask the ai", "generate next turn",
    "generate the next scene", "reload turn",
]

TURN_ACTION_META_PHRASES_ZH = [
    "推进剧情", "推进回合", "生成下一回合", "生成下一幕", "问ai", "问AI",
]

TURN_ACTION_CLEARLY_UNRELATED_PHRASES = [
    "buy a spaceship", "cast a spell", "fight a dragon", "hack the database",
    "leave the planet", "summon a dragon", "teleport away",
]

TURN_ACTION_CLEARLY_UNRELATED_PHRASES_ZH = [
    "买飞船", "打龙", "打怪", "黑进数据库", "离开地球", "召唤巨龙",
]

TURN_ACTION_UNSAFE_PHRASES = [
    "abuse", "blackmail", "hit", "hurt them", "hurt her", "hurt him",
    "intimidate", "kill", "punch", "shove", "slap", "threat", "threaten",
]

TURN_ACTION_UNSAFE_PHRASES_ZH = [
    "威胁", "打他", "打她", "打人", "伤害他", "伤害她", "辱骂", "恐吓", "勒索",
]

TURN_ACTION_EXPLICIT_ACTION_MARKERS_ZH = [
    "\u6211\u4f1a", "\u6211\u8981", "\u6211\u95ee", "\u6211\u544a\u8bc9",
    "\u6211\u5efa\u8bae", "\u6211\u63d0\u51fa", "\u6211\u9080\u8bf7",
    "\u6211\u786e\u8ba4", "\u6211\u89e3\u91ca", "\u6211\u63a5\u53d7",
    "\u6211\u62d2\u7edd", "\u6211\u9053\u6b49",
]

TURN_ACTION_EXPLICIT_ACTION_MARKERS_EN = [
    "i will", "i ask", "i tell", "i suggest", "i propose", "i invite",
    "i confirm", "i explain", "i accept", "i refuse", "i apologize",
]

TURN_ACTION_RELATIONSHIP_PROGRESSION_MARKERS_ZH = [
    "\u8fbe\u6210\u5171\u8bc6", "\u51b3\u5b9a", "\u540c\u610f", "\u8ba1\u5212",
    "\u5b89\u6392", "\u7ea6\u5b9a", "\u539f\u8c05", "\u548c\u597d",
    "\u63a5\u53d7", "\u59a5\u534f", "\u4e00\u8d77", "\u5f00\u59cb",
    "\u7ed3\u675f", "\u89e3\u51b3", "\u7f13\u548c", "\u4fee\u590d",
    "\u65c5\u884c", "\u89c1\u9762", "\u4e0b\u5468", "\u4ee5\u540e",
    "\u5171\u540c\u51b3\u5b9a",
]

TURN_ACTION_RELATIONSHIP_PROGRESSION_MARKERS_EN = [
    "agreed", "planned", "decided", "forgave", "accepted", "resolved",
    "together", "scheduled", "trip", "next week", "reconciled",
]

TURN_ACTION_STRONG_PROGRESSION_MARKERS_ZH = [
    "\u8fbe\u6210\u5171\u8bc6", "\u51b3\u5b9a", "\u540c\u610f", "\u8ba1\u5212",
    "\u5b89\u6392", "\u7ea6\u5b9a", "\u539f\u8c05", "\u548c\u597d",
    "\u59a5\u534f", "\u89e3\u51b3", "\u7f13\u548c", "\u4fee\u590d",
    "\u65c5\u884c", "\u89c1\u9762", "\u5171\u540c\u51b3\u5b9a",
]

TURN_ACTION_STRONG_PROGRESSION_MARKERS_EN = [
    "agreed", "planned", "decided", "forgave", "accepted", "resolved",
    "scheduled", "trip", "reconciled",
]

TURN_ACTION_FUTURE_EVENT_MARKERS_ZH = [
    "\u4e0b\u5468", "\u660e\u5929", "\u4e4b\u540e", "\u4ee5\u540e",
    "\u4e0b\u4e00\u6b21", "\u672a\u6765",
]

TURN_ACTION_FUTURE_EVENT_MARKERS_EN = [
    "soon", "next", "later", "upcoming", "tomorrow", "next week",
]

TURN_ACTION_RELATIONSHIP_ENTITIES_ZH = [
    "\u6211\u4eec", "\u4ed6", "\u5979", "\u7537\u670b\u53cb",
    "\u5973\u670b\u53cb", "\u4f34\u4fa3", "\u5bf9\u65b9",
]

TURN_ACTION_RELATIONSHIP_ENTITIES_EN = [
    "we", "us", "our", "partner", "boyfriend", "girlfriend",
    "he", "she", "him", "her",
]


def _contains_prefixed_word(words, prefixes):
    return any(
        word.startswith(prefix)
        for word in words
        for prefix in prefixes
    )


def _detect_action_validation_language(text):
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    latin_count = len(re.findall(r"[A-Za-z]", text or ""))
    if cjk_count >= max(2, latin_count):
        return "zh"
    return "en"


def _analyze_turn_action_text(text):
    stripped = (text or "").strip()
    lowered = stripped.lower()
    words = re.findall(r"[a-zA-Z']+", lowered)
    cjk_char_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    language = _detect_action_validation_language(stripped)
    return stripped, lowered, words, cjk_char_count, language


def _contains_english_term(lowered, term):
    normalized_term = str(term or "").strip().lower()
    if normalized_term == "":
        return False
    if " " in normalized_term:
        return normalized_term in lowered
    return re.search(rf"\b{re.escape(normalized_term)}\b", lowered) is not None


def _has_explicit_action_marker(text, lowered):
    compact_text = re.sub(r"\s+", "", text or "")
    return (
        any(marker in compact_text for marker in TURN_ACTION_EXPLICIT_ACTION_MARKERS_ZH)
        or any(_contains_english_term(lowered, marker) for marker in TURN_ACTION_EXPLICIT_ACTION_MARKERS_EN)
    )


def _has_relationship_entity_signal(text, lowered):
    return (
        any(marker in text for marker in TURN_ACTION_RELATIONSHIP_ENTITIES_ZH)
        or any(_contains_english_term(lowered, marker) for marker in TURN_ACTION_RELATIONSHIP_ENTITIES_EN)
    )


def _is_relationship_progression(text, lowered):
    has_progression_marker = (
        any(marker in text for marker in TURN_ACTION_RELATIONSHIP_PROGRESSION_MARKERS_ZH)
        or any(_contains_english_term(lowered, marker) for marker in TURN_ACTION_RELATIONSHIP_PROGRESSION_MARKERS_EN)
    )
    has_strong_progression_marker = (
        any(marker in text for marker in TURN_ACTION_STRONG_PROGRESSION_MARKERS_ZH)
        or any(_contains_english_term(lowered, marker) for marker in TURN_ACTION_STRONG_PROGRESSION_MARKERS_EN)
    )
    return has_strong_progression_marker or (
        has_progression_marker and _has_relationship_entity_signal(text, lowered)
    )


def _is_future_event_progression(text, lowered):
    has_future_marker = (
        any(marker in text for marker in TURN_ACTION_FUTURE_EVENT_MARKERS_ZH)
        or any(_contains_english_term(lowered, marker) for marker in TURN_ACTION_FUTURE_EVENT_MARKERS_EN)
    )
    return has_future_marker and _has_relationship_entity_signal(text, lowered)


def _get_turn_action_length_metrics(text, words, cjk_char_count, language):
    compact_char_count = len(re.sub(r"\s+", "", text or ""))
    english_char_count = len(text or "")
    english_word_count = len(words or [])

    if language == "zh":
        validation_char_count = cjk_char_count
        length_passed = 15 <= cjk_char_count <= 100
        too_short = cjk_char_count < 15
        too_long = cjk_char_count > 100
    else:
        validation_char_count = english_char_count
        length_passed = english_word_count >= 9 and english_char_count <= 220
        too_short = english_word_count < 9
        too_long = english_char_count > 220

    return {
        "validation_char_count": validation_char_count,
        "compact_char_count": compact_char_count,
        "english_char_count": english_char_count,
        "english_word_count": english_word_count,
        "validation_length_passed": length_passed,
        "validation_too_short": too_short,
        "validation_too_long": too_long,
    }


def _has_social_action_signal(text, lowered, words):
    return (
        _contains_prefixed_word(words, TURN_ACTION_SOCIAL_PREFIXES)
        or any(phrase in lowered for phrase in TURN_ACTION_SOCIAL_PHRASES)
        or any(marker in text for marker in TURN_ACTION_SOCIAL_MARKERS_ZH)
    )


def _has_counterpart_or_context_signal(text, lowered, words, cjk_char_count):
    if any(term in lowered for term in TURN_ACTION_COUNTERPART_TERMS):
        return True

    if any(term in text for term in TURN_ACTION_COUNTERPART_TERMS_ZH):
        return True

    if any(quote_mark in text for quote_mark in ['"', "“", "”", "‘", "’", "：", ":"]):
        return True

    content_words = [word for word in words if len(word) >= 3]
    return len(content_words) >= 5 or cjk_char_count >= 10


def _is_meta_turn_action(lowered):
    return any(phrase in lowered for phrase in TURN_ACTION_META_PHRASES) or any(
        phrase in lowered for phrase in TURN_ACTION_META_PHRASES_ZH
    )


def _is_clearly_unrelated_turn_action(lowered):
    return any(phrase in lowered for phrase in TURN_ACTION_CLEARLY_UNRELATED_PHRASES) or any(
        phrase in lowered for phrase in TURN_ACTION_CLEARLY_UNRELATED_PHRASES_ZH
    )


def _is_unsafe_turn_action(lowered):
    return any(phrase in lowered for phrase in TURN_ACTION_UNSAFE_PHRASES) or any(
        phrase in lowered for phrase in TURN_ACTION_UNSAFE_PHRASES_ZH
    )


def _build_local_action_validation_feedback(text, language, detail):
    if language == "zh":
        prefix = f"这个行动目前还不能推进剧情：“{text}”。"
        concrete_prompt = "请描述你接下来采取的一个具体行动，比如你会说什么、问什么、提出什么、接受什么、拒绝什么或建议什么。"
    else:
        prefix = f"I cannot advance the story from this action yet: \"{text}\"."
        concrete_prompt = (
            "Please describe one concrete action you take next, such as what you say, ask, offer, accept, refuse, or suggest."
        )

    detail = str(detail or "").strip()
    if detail:
        return f"{prefix} {detail} {concrete_prompt}"
    return f"{prefix} {concrete_prompt}"


def _build_turn_action_length_feedback(language, issue):
    if issue == "too_long":
        if language == "zh":
            return (
                "\u4f60\u7684\u8f93\u5165\u592a\u957f\u4e86\u3002"
                "\u8bf7\u7528\u4e00\u53e5\u7b80\u6d01\u3001\u5177\u4f53\u7684\u884c\u52a8"
                "\u63cf\u8ff0\u6765\u63a8\u8fdb\u5267\u60c5\uff08100\u5b57\u4ee5\u5185\uff09\u3002"
            )
        return (
            "Your input is too long. Please describe one clear action to move "
            "the story forward (within 220 characters)."
        )

    if language == "zh":
        return (
            "\u4f60\u7684\u8f93\u5165\u592a\u77ed\u4e86\u3002"
            "\u8bf7\u7528\u4e00\u53e5\u66f4\u5b8c\u6574\u3001\u5177\u4f53\u7684"
            "\u884c\u52a8\u6216\u5267\u60c5\u63a8\u8fdb\u63cf\u8ff0\u6765\u63a8\u8fdb"
            "\u5267\u60c5\uff08\u81f3\u5c1115\u4e2a\u6c49\u5b57\uff09\u3002"
        )
    return (
        "Your input is too short. Please describe one fuller, concrete action "
        "or story progression move (at least 9 words)."
    )


def _log_local_action_validation(language, passed, reason, **extra_fields):
    _log_provider_event(
        "action_validation_local",
        action_validation_language=language,
        action_validation_passed=bool(passed),
        action_validation_reason=reason,
        **extra_fields,
    )


def _validate_turn_action_local(action_text, current_session, user_role):
    text, lowered, words, cjk_char_count, language = _analyze_turn_action_text(action_text)

    has_social_action = _has_social_action_signal(text, lowered, words)
    has_emotion_keyword = (
        any(keyword in lowered for keyword in TURN_ACTION_EMOTION_KEYWORDS)
        or any(keyword in text for keyword in TURN_ACTION_EMOTION_KEYWORDS_ZH)
    )
    is_short = (len(words) < 2 and cjk_char_count < 4) or len(text) < 4
    is_vague_phrase = (
        any(phrase in lowered for phrase in TURN_ACTION_VAGUE_PHRASES)
        or any(phrase in text for phrase in TURN_ACTION_VAGUE_PHRASES_ZH)
    )
    has_counterpart_or_context = _has_counterpart_or_context_signal(
        text, lowered, words, cjk_char_count
    )

    if is_short:
        _log_local_action_validation(language, False, "too_short")
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, "")
        }

    if _is_meta_turn_action(lowered):
        detail = (
            "请描述你角色接下来会采取的具体行动，而不是对应用或 AI 的指令。"
            if language == "zh"
            else "Please describe one concrete action your character takes next, not a command to the app or AI."
        )
        _log_local_action_validation(language, False, "meta_command")
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if _is_clearly_unrelated_turn_action(lowered):
        detail = (
            "请把它保持为当前角色扮演中的一个可信的人际互动动作。"
            if language == "zh"
            else "Please keep it to a believable interpersonal move in the current role-play."
        )
        _log_local_action_validation(language, False, "clearly_unrelated")
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if _is_unsafe_turn_action(lowered):
        detail = (
            "请描述一个具体的下一步，但不要包含暴力、胁迫或辱骂。"
            if language == "zh"
            else "Please describe a concrete next move that is not violent, coercive, or abusive."
        )
        _log_local_action_validation(language, False, "unsafe")
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if not has_social_action:
        if has_emotion_keyword:
            detail = (
                "这句话主要表达了感受，但还没有说明你接下来具体会怎么做。"
                if language == "zh"
                else "It mainly expresses a feeling, but it does not yet describe a concrete move."
            )
            log_reason = "emotion_without_action"
        else:
            detail = (
                "这句话还没有清楚说明一个可执行的人际互动动作。"
                if language == "zh"
                else "It does not yet describe one clear interpersonal action."
            )
            log_reason = "no_concrete_action"

        _log_local_action_validation(language, False, log_reason)
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if is_vague_phrase or (
        has_social_action
        and len(words) < 5
        and cjk_char_count < 8
        and not has_counterpart_or_context
    ):
        detail = (
            "你的意图可以理解，但这个动作还是太模糊了。"
            if language == "zh"
            else "The intention is understandable, but the move is still too vague."
        )
        _log_local_action_validation(language, False, "too_vague")
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    _log_local_action_validation(language, True, "valid")
    return {
        "is_valid": True,
        "feedback": ""
    }


def _build_turn_action_result(
    *,
    accepted,
    reason,
    next_situation="",
    risk_flags=None,
    coach_note=""
):
    normalized_risk_flags = []
    for flag in risk_flags or []:
        normalized_flag = str(flag or "").strip()
        if normalized_flag and normalized_flag not in normalized_risk_flags:
            normalized_risk_flags.append(normalized_flag)

    return {
        "accepted": bool(accepted),
        "reason": str(reason or "").strip(),
        "next_situation": str(next_situation or "").strip() if accepted else "",
        "risk_flags": normalized_risk_flags,
        "coach_note": str(coach_note or "").strip(),
    }


def _get_local_turn_action_risk_flags(action_text, current_session, user_role):
    text, lowered, words, cjk_char_count, _language = _analyze_turn_action_text(action_text)

    risk_flags = []

    if _is_unsafe_turn_action(lowered) or any(
        keyword in lowered
        for keyword in ["violent", "violence", "scream at", "yell at", "abusive"]
    ):
        risk_flags.append("unsafe")

    if any(keyword in lowered for keyword in ["yell", "scream", "blame", "attack", "punish"]):
        risk_flags.append("escalatory")

    if (len(words) < 2 and cjk_char_count < 4) or len(text) < 4:
        risk_flags.append("too brief")

    if any(phrase in lowered for phrase in TURN_ACTION_VAGUE_PHRASES) or any(
        phrase in text for phrase in TURN_ACTION_VAGUE_PHRASES_ZH
    ):
        risk_flags.append("too vague")

    has_social_action = _has_social_action_signal(text, lowered, words)
    has_counterpart_or_context = _has_counterpart_or_context_signal(
        text, lowered, words, cjk_char_count
    )

    if not has_social_action:
        risk_flags.append("not actionable")
    elif len(words) < 5 and cjk_char_count < 8 and not has_counterpart_or_context:
        risk_flags.append("too vague")

    if _is_meta_turn_action(lowered) or _is_clearly_unrelated_turn_action(lowered):
        risk_flags.append("unrelated")

    return risk_flags


def _get_local_turn_action_risk_flags(action_text, current_session, user_role):
    text, lowered, words, cjk_char_count, language = _analyze_turn_action_text(action_text)
    length_metrics = _get_turn_action_length_metrics(
        text=text,
        words=words,
        cjk_char_count=cjk_char_count,
        language=language
    )

    risk_flags = []

    if _is_unsafe_turn_action(lowered) or any(
        keyword in lowered
        for keyword in ["violent", "violence", "scream at", "yell at", "abusive"]
    ):
        risk_flags.append("unsafe")

    if any(keyword in lowered for keyword in ["yell", "scream", "blame", "attack", "punish"]):
        risk_flags.append("escalatory")

    if length_metrics["validation_too_long"]:
        risk_flags.append("too long")
    elif length_metrics["validation_too_short"]:
        risk_flags.append("too brief")

    if any(phrase in lowered for phrase in TURN_ACTION_VAGUE_PHRASES) or any(
        phrase in text for phrase in TURN_ACTION_VAGUE_PHRASES_ZH
    ):
        risk_flags.append("too vague")

    has_social_action = _has_social_action_signal(text, lowered, words)
    has_explicit_action = _has_explicit_action_marker(text, lowered)
    relationship_progression_valid = _is_relationship_progression(text, lowered)
    future_progression_valid = _is_future_event_progression(text, lowered)

    if not (has_social_action or has_explicit_action or relationship_progression_valid or future_progression_valid):
        risk_flags.append("not actionable")

    if _is_meta_turn_action(lowered) or _is_clearly_unrelated_turn_action(lowered):
        risk_flags.append("unrelated")

    normalized_risk_flags = []
    for flag in risk_flags:
        if flag not in normalized_risk_flags:
            normalized_risk_flags.append(flag)
    return normalized_risk_flags


def _validate_turn_action_local(action_text, current_session, user_role):
    text, lowered, words, cjk_char_count, language = _analyze_turn_action_text(action_text)
    length_metrics = _get_turn_action_length_metrics(
        text=text,
        words=words,
        cjk_char_count=cjk_char_count,
        language=language
    )
    log_fields = {
        "validation_char_count": length_metrics["validation_char_count"],
        "validation_length_passed": length_metrics["validation_length_passed"],
        "validation_too_long": length_metrics["validation_too_long"],
    }

    has_social_action = _has_social_action_signal(text, lowered, words)
    has_explicit_action = _has_explicit_action_marker(text, lowered)
    relationship_progression_valid = _is_relationship_progression(text, lowered)
    future_progression_valid = _is_future_event_progression(text, lowered)
    action_valid = has_social_action or has_explicit_action
    has_emotion_keyword = (
        any(keyword in lowered for keyword in TURN_ACTION_EMOTION_KEYWORDS)
        or any(keyword in text for keyword in TURN_ACTION_EMOTION_KEYWORDS_ZH)
    )
    is_vague_phrase = (
        any(phrase in lowered for phrase in TURN_ACTION_VAGUE_PHRASES)
        or any(phrase in text for phrase in TURN_ACTION_VAGUE_PHRASES_ZH)
    )

    if length_metrics["validation_too_long"]:
        _log_local_action_validation(language, False, "too_long", **log_fields)
        return {
            "is_valid": False,
            "feedback": _build_turn_action_length_feedback(language, "too_long")
        }

    if length_metrics["validation_too_short"]:
        _log_local_action_validation(language, False, "too_short", **log_fields)
        return {
            "is_valid": False,
            "feedback": _build_turn_action_length_feedback(language, "too_short")
        }

    if _is_meta_turn_action(lowered):
        detail = (
            "\u8bf7\u63cf\u8ff0\u4f60\u89d2\u8272\u63a5\u4e0b\u6765\u4f1a\u91c7\u53d6\u7684\u5177\u4f53\u884c\u52a8\uff0c"
            "\u800c\u4e0d\u662f\u5bf9\u5e94\u7528\u6216 AI \u7684\u6307\u4ee4\u3002"
            if language == "zh"
            else "Please describe one concrete action your character takes next, not a command to the app or AI."
        )
        _log_local_action_validation(language, False, "meta_command", **log_fields)
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if _is_clearly_unrelated_turn_action(lowered):
        detail = (
            "\u8bf7\u628a\u5b83\u4fdd\u6301\u4e3a\u5f53\u524d\u89d2\u8272\u626e\u6f14\u4e2d\u7684\u4e00\u4e2a"
            "\u53ef\u4fe1\u7684\u4eba\u9645\u4e92\u52a8\u52a8\u4f5c\u3002"
            if language == "zh"
            else "Please keep it to a believable interpersonal move in the current role-play."
        )
        _log_local_action_validation(language, False, "clearly_unrelated", **log_fields)
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if _is_unsafe_turn_action(lowered):
        detail = (
            "\u8bf7\u63cf\u8ff0\u4e00\u4e2a\u5177\u4f53\u7684\u4e0b\u4e00\u6b65\uff0c"
            "\u4f46\u4e0d\u8981\u5305\u542b\u66b4\u529b\u3001\u80c1\u8feb\u6216\u8fb1\u9a82\u3002"
            if language == "zh"
            else "Please describe a concrete next move that is not violent, coercive, or abusive."
        )
        _log_local_action_validation(language, False, "unsafe", **log_fields)
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if length_metrics["validation_length_passed"] and (
        action_valid or relationship_progression_valid or future_progression_valid
    ):
        if action_valid:
            log_reason = "explicit_action" if has_explicit_action else "social_action"
        elif relationship_progression_valid:
            log_reason = "relationship_progression"
        else:
            log_reason = "future_event_progression"
        _log_local_action_validation(language, True, log_reason, **log_fields)
        return {
            "is_valid": True,
            "feedback": ""
        }

    if not action_valid and not relationship_progression_valid and not future_progression_valid:
        if has_emotion_keyword:
            detail = (
                "\u8fd9\u53e5\u8bdd\u4e3b\u8981\u8868\u8fbe\u4e86\u611f\u53d7\uff0c"
                "\u4f46\u8fd8\u6ca1\u6709\u8bf4\u660e\u4f60\u63a5\u4e0b\u6765\u5177\u4f53\u4f1a\u600e\u4e48\u505a\u3002"
                if language == "zh"
                else "It mainly expresses a feeling, but it does not yet describe a concrete move."
            )
            log_reason = "emotion_without_action"
        else:
            detail = (
                "\u8fd9\u6bb5\u8f93\u5165\u8fd8\u6ca1\u6709\u5f62\u6210\u6e05\u6670\u7684\u884c\u52a8"
                "\u6216\u5267\u60c5\u63a8\u8fdb\u3002\u8bf7\u63cf\u8ff0\u4f60\u4f1a\u505a\u4ec0\u4e48\uff0c"
                "\u6216\u53cc\u65b9\u5173\u7cfb\u8fdb\u5165\u4e86\u4ec0\u4e48\u65b0\u7684\u9636\u6bb5\u3002"
                if language == "zh"
                else "It does not yet describe one clear action or relationship progression."
            )
            log_reason = "no_action_or_progression"

        _log_local_action_validation(language, False, log_reason, **log_fields)
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    if is_vague_phrase:
        detail = (
            "\u4f60\u7684\u8f93\u5165\u592a\u7b3c\u7edf\u4e86\u3002"
            "\u8bf7\u628a\u5b83\u6539\u6210\u4e00\u53e5\u5177\u4f53\u3001\u53ef\u6267\u884c\u7684\u884c\u52a8\uff0c"
            "\u6216\u660e\u786e\u8bf4\u660e\u53cc\u65b9\u5173\u7cfb\u8fdb\u5165\u4e86\u4ec0\u4e48\u65b0\u7684\u9636\u6bb5\u3002"
            if language == "zh"
            else "The input is still too vague. Please turn it into one specific action or a clear relationship progression move."
        )
        _log_local_action_validation(language, False, "too_vague", **log_fields)
        return {
            "is_valid": False,
            "feedback": _build_local_action_validation_feedback(text, language, detail)
        }

    _log_local_action_validation(language, False, "failed_progression_gate", **log_fields)
    return {
        "is_valid": False,
        "feedback": _build_local_action_validation_feedback(
            text,
            language,
            (
                "\u8bf7\u628a\u8fd9\u53e5\u8bdd\u6539\u6210\u4e00\u4e2a\u6e05\u6670\u3001\u5177\u4f53\u7684\u884c\u52a8\uff0c"
                "\u6216\u8005\u660e\u786e\u8bf4\u660e\u53cc\u65b9\u5173\u7cfb\u5982\u4f55\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5\u3002"
                if language == "zh"
                else "Please turn this into one clear action or explain how the relationship has moved into a new stage."
            )
        )
    }


def _evaluate_turn_action_local(
    action_text,
    current_session,
    user_role,
    recent_turn_history=None
):
    text = (action_text or "").strip()
    if text == "":
        return _build_turn_action_result(
            accepted=False,
            reason="Your action cannot be empty.",
            risk_flags=["not actionable"],
            coach_note="Describe one specific thing you would actually say or do."
        )

    risk_flags = _get_local_turn_action_risk_flags(
        action_text=text,
        current_session=current_session,
        user_role=user_role
    )
    lowered_flags = {flag.lower() for flag in risk_flags}

    if "unsafe" in lowered_flags:
        return _build_turn_action_result(
            accepted=False,
            reason="This action is too unsafe or threatening to advance the scenario.",
            risk_flags=risk_flags,
            coach_note=(
                "Revise it into a concrete but non-threatening response that addresses the conflict "
                "without intimidation or abuse."
            )
        )

    validation = _validate_turn_action_local(
        action_text=text,
        current_session=current_session,
        user_role=user_role
    )
    if not validation["is_valid"]:
        coach_note = validation["feedback"] or (
            "Make the action more concrete, relevant to the conflict, and specific enough "
            "for the other person to respond to."
        )
        return _build_turn_action_result(
            accepted=False,
            reason=coach_note,
            risk_flags=risk_flags,
            coach_note=(
                "Try describing exactly what you would say or do, who you would address, "
                "and what shift you are trying to create."
            )
        )

    next_situation = _generate_next_situation_local(
        current_session=current_session,
        user_role=user_role,
        action_text=text
    )

    return _build_turn_action_result(
        accepted=True,
        reason="This action is concrete and relevant enough to move the situation forward.",
        next_situation=next_situation,
        risk_flags=risk_flags,
        coach_note="Stay specific and be ready for the other person to respond with tension, hesitation, or pushback."
    )


def _generate_dynamic_ai_feedback_local(
    user_role,
    user_text,
    current_turn,
    current_situation,
    current_session=None,
    user_profile=None,
    recent_turn_history=None
):
    signal = classify_action_signal(user_text)
    role_label = get_role_label(user_role)
    profile_context = format_user_profile_context(user_profile)
    recent_history_context = format_recent_turn_history(recent_turn_history)

    if signal == "repair":
        coaching_focus = "That move can reduce defensiveness, but it will only feel credible if your wording is specific and accountable."
    elif signal == "clarify":
        coaching_focus = "Clarifying can be productive here, especially if you separate facts, emotions, and requests instead of blending them together."
    elif signal == "escalate":
        coaching_focus = "That move may create short-term control, but it also risks hardening the other person's stance and narrowing the room for repair."
    else:
        coaching_focus = "There is room to explore, but you may need to state your intention more clearly so the next move changes the interaction instead of prolonging uncertainty."

    personalization = ""
    if profile_context:
        personalization = f" Use your profile context ({profile_context}) as a lens, but do not let it become a fixed script."

    continuity = ""
    if recent_history_context:
        continuity = " Also consider how this response fits the recent progression instead of treating the turn as isolated."

    scenario_context = ""
    if current_session:
        scenario_context = " ".join([
            str(current_session.get("title", "") or ""),
            str(current_session.get("conflict", "") or ""),
        ]).strip()

    scenario_prefix = ""
    if scenario_context:
        scenario_prefix = f"In this situation ({scenario_context}), "

    return (
        f"{scenario_prefix}from {role_label}'s perspective in turn {current_turn}, "
        f"it makes sense that this moment feels charged. You wrote: \"{user_text.strip()}\". "
        f"{coaching_focus}{personalization}{continuity} "
        "A grounded next move would be to name what you actually know, avoid guessing the other person's intention, "
        "and choose one specific question or request you can make next."
    )


def _build_llm_coach_feedback_messages(
    current_session,
    user_role,
    user_text,
    current_turn,
    current_situation,
    private_role_brief="",
    user_profile=None,
    recent_turn_history=None,
    recent_coach_history=None,
    debug_trace_id=None
):
    role_label = get_role_label(user_role)
    profile_context = format_user_profile_context(user_profile) or "None provided."
    latest_user_language = infer_latest_user_message_language(user_text)
    latest_user_message_language = describe_latest_user_message_language(
        latest_user_language
    )
    prior_visible_user_message_count = count_prior_visible_user_messages(
        recent_coach_history
    )
    first_coach_reply = prior_visible_user_message_count == 0
    prompt_mode = "first" if first_coach_reply else "follow_up"
    recent_history_context = format_recent_turn_history(recent_turn_history)
    if recent_history_context == "":
        recent_history_context = "No recent turn history available."
    role_brief_history_context = format_role_brief_history_for_prompt(
        current_session,
        user_role,
        max_recent_turns=2
    )
    coach_history_context = format_recent_coach_history(recent_coach_history)
    if coach_history_context == "":
        coach_history_context = "No recent coach conversation history available."
    rag_notes = []
    rag_notes_context = ""
    if first_coach_reply:
        rag_query = build_coach_rag_query(
            current_session=current_session,
            user_role=user_role,
            user_text=user_text,
            user_profile=user_profile,
            recent_turn_history=recent_turn_history
        )
        rag_notes = retrieve_relevant_notes(rag_query, top_k=4)
        rag_notes_context = format_rag_notes_for_prompt(rag_notes)
    retrieved_doc_count = len(rag_notes)
    rag_preview = ""
    if rag_notes_context.strip() and not rag_notes_context.startswith("No relevant local guidance"):
        rag_preview = _short_debug_text(rag_notes_context, 200)
    _log_provider_event(
        "ai_coach_rag_context_built",
        debug_trace_id=debug_trace_id,
        rag_enabled=first_coach_reply,
        first_coach_reply=first_coach_reply,
        retrieved_note_count=retrieved_doc_count,
        retrieved_note_titles=[note.get("title") for note in rag_notes],
        retrieved_note_sources=[note.get("relative_path") for note in rag_notes],
        retrieved_note_preview=rag_preview
    )

    local_style_anchor = _generate_dynamic_ai_feedback_local(
        user_role=user_role,
        user_text=user_text,
        current_turn=current_turn,
        current_situation=current_situation,
        current_session=current_session,
        user_profile=user_profile,
        recent_turn_history=recent_turn_history
    )

    first_prompt_style = (
        "This is the first visible user message in the private coaching conversation. "
        "Use the fuller structured coaching style, but keep it natural rather than rigid. "
        "Do not make the first reply too short. Give enough substance to help the user understand the situation and choose a grounded next move.\n"
        "For the first user message, the coach should normally cover these ideas naturally unless the user explicitly asks for a very narrow answer:\n"
        "1. Objective situation: briefly analyze the observable facts of the scenario, separate what is known from what is assumed, and avoid mind-reading.\n"
        "2. User feelings and expectations: help the user recognize what they may be feeling, hoping for, needing, or expecting. Use profile details, MBTI, and profile notes gently as context, not as a fixed diagnosis.\n"
        "3. Perspective-taking: help the user consider how the other person may experience the same situation, but present this as possibility rather than certainty. The first reply should include at least some perspective-taking.\n"
        "4. Methodology for action: offer one practical communication or decision-making method that fits the current situation. Keep theory light and applied.\n"
        "5. Advice: end with one or two concrete next-step suggestions, and include example wording when useful."
    )
    follow_up_prompt_style = (
        "This is an ongoing private coaching conversation. "
        "Use Recent AI Coach conversation history to continue naturally from the previous exchange.\n"
        "For follow-up messages:\n"
        "- Do not restart the full first-message framework.\n"
        "- Do not re-explain all objective facts unless the user introduces a new major issue.\n"
        "- Do not repeat the same advice in a new format.\n"
        "- Pick up from the user's latest response.\n"
        "- Help the user clarify, refine, or take the next step.\n"
        "- Keep the response shorter than the first reply unless the user asks for depth.\n"
        "- End with one useful move, concrete suggestion, or reflective question.\n"
        "- It is okay to focus mostly on one useful next move if that is what the conversation needs."
    )
    prompt_mode_instruction = (
        first_prompt_style
        if prompt_mode == "first"
        else follow_up_prompt_style
    )

    system_message = (
        "You are a supportive communication coach for a role-play decision-training tool. "
        "Your job is to help the user understand the current interpersonal situation, notice their own feelings and expectations, "
        "consider what the other person may be experiencing, and choose a grounded next move. "
        "The AI Coach Chat is a continuous conversation. Use recent coach conversation history to decide whether this is a first message or a follow-up. "
        "If it is a follow-up, continue from what has already been discussed instead of restarting the full analysis. "
        "Always reply in the same language as the latest user message. The latest user message language has priority over profile language, MBTI/profile notes language, prior coach history language, retrieved note language, and scenario text language. "
        "If the latest user message is mixed-language, use the dominant language of that latest message. "
        "Use retrieved knowledge notes only when relevant and only as background guidance. "
        "Use retrieved knowledge notes only for the first coach reply in a conversation. For follow-up replies, rely on the existing coach conversation history instead of reintroducing retrieved notes. "
        "Do not force a fixed framework. Do not overuse repetitive coaching formulas. Do not always ask the same three questions. "
        "Do not diagnose. Do not moralize. Do not claim to know what the other person truly thinks. "
        "Be practical, emotionally aware, and specific to the current scenario. "
        "Respond only with coaching feedback for the current user's private reflection. "
        "Do not advance the story, do not produce shared-chat dialogue, and do not role-play the other user. "
        "Keep the response warm, grounded, and concise."
    )
    user_message = (
        f"Scenario title: {current_session.get('title', '')}\n"
        f"Scenario context: {current_session.get('context', '')}\n"
        f"Scenario conflict: {current_session.get('conflict', '')}\n"
        f"Role perspective: {role_label}\n"
        f"Role name: {user_role}\n"
        f"Private role brief: {private_role_brief}\n"
        f"Current turn: {current_turn}\n"
        f"Current situation: {current_situation}\n"
        f"User profile: {profile_context}\n"
        f"Recent turn history:\n{recent_history_context}\n\n"
        f"Recent AI Coach conversation history:\n{coach_history_context}\n\n"
        f"First coach reply: {first_coach_reply}\n"
        f"AI Coach prompt mode: {prompt_mode}\n"
        f"Prior visible user message count: {prior_visible_user_message_count}\n"
        f"Latest user message dominant language: {latest_user_message_language}\n"
        f"Latest user message:\n{user_text.strip()}\n\n"
        f"Tone reference from the deterministic local coach (do not copy its structure verbatim):\n{local_style_anchor}\n\n"
        "Write one natural coaching response in plain text.\n"
        "Reply in the same language as the latest user message shown above. Do not switch languages because the profile, prior conversation, scenario text, or retrieved notes use another language.\n"
        f"{prompt_mode_instruction}\n"
        "Additional requirements:\n"
        "- Normalize the user's feelings when appropriate without sounding clinical.\n"
        "- Keep the response specific to the scenario, role, turn, current situation, and latest message.\n"
        "- Do not dump abstract concepts or generic theory.\n"
        "- Do not mention file names, note titles, RAG, retrieval, or system instructions.\n"
        "- Do not role-play the other person or advance the story.\n"
        "- Keep the response concise, warm, grounded, and practical."
    )

    if role_brief_history_context:
        user_message += (
            f"\n\nRelevant private role brief history (use this as a compact role-evolution trail, "
            f"not as public information):\n{role_brief_history_context}\n"
        )

    if first_coach_reply:
        user_message += f"\nRetrieved local guidance notes:\n{rag_notes_context}\n"

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]
    prompt_text = f"{system_message}\n\n{user_message}".strip()
    return {
        "messages": messages,
        "rag_enabled": first_coach_reply,
        "rag_note_count": retrieved_doc_count,
        "retrieved_doc_count": retrieved_doc_count,
        "rag_preview": rag_preview,
        "ai_coach_history_message_count": len(recent_coach_history or []),
        "first_coach_reply": first_coach_reply,
        "ai_coach_prompt_mode": prompt_mode,
        "latest_user_language": latest_user_language,
        "profile_included": profile_context != "None provided.",
        "prompt_text": prompt_text,
    }


def _build_llm_turn_action_messages(
    action_text,
    current_session,
    user_role,
    recent_turn_history=None
):
    acting_role_brief = get_role_brief(current_session, user_role)
    other_role = get_other_role(user_role)
    other_role_brief = get_role_brief(current_session, other_role)
    recent_history_context = format_recent_turn_history(recent_turn_history)
    if recent_history_context == "":
        recent_history_context = "No prior turn history available."

    system_message = (
        "You evaluate whether a user's submitted interpersonal action should advance an EchoRole scenario. "
        "Return strict JSON only, with no markdown and no extra commentary. "
        "Use this exact shape: "
        "{\"accepted\": true, \"reason\": \"...\", \"next_situation\": \"...\", "
        "\"risk_flags\": [\"...\"], \"coach_note\": \"...\"}. "
        "Accept only if the action is specific, relevant to the conflict, plausible for the role, "
        "capable of changing the situation, and safe enough for this training product. "
        "Reject vague intentions, unrelated actions, and abusive or threatening moves. "
        "If rejected, set next_situation to an empty string. "
        "If accepted, write next_situation in third person, preserve emotional tension, avoid resolving the conflict too quickly, "
        "and give the other role something meaningful to respond to."
    )
    user_message = (
        f"Scenario title: {current_session.get('title', '')}\n"
        f"Scenario context: {current_session.get('context', '')}\n"
        f"Scenario conflict: {current_session.get('conflict', '')}\n"
        f"Current turn number: {current_session.get('current_turn', 1)}\n"
        f"Current situation: {current_session.get('current_situation', '')}\n"
        f"Acting role: {user_role}\n"
        f"Acting role brief: {acting_role_brief}\n"
        f"Other role brief: {other_role_brief}\n"
        f"Recent turn history:\n{recent_history_context}\n\n"
        f"Submitted action:\n{(action_text or '').strip()}\n\n"
        "Validation criteria:\n"
        "- Accept only if the action is concrete enough to act out.\n"
        "- Accept only if it is relevant to the scenario and current conflict.\n"
        "- Accept only if it is plausible for the acting role.\n"
        "- Reject actions that are too vague, purely emotional, unrelated, or not actionable.\n"
        "- Prefer safe rejection for abusive, threatening, or unsafe moves.\n"
        "- If accepted, next_situation must describe what happened after the action and what pressure remains.\n"
        "- Keep the reason concise and user-facing.\n"
        "- risk_flags should use short labels such as: too vague, unrelated, escalatory, unsafe, not actionable.\n"
        "- coach_note should be one short practical guidance sentence.\n"
        "Return JSON only."
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def _build_llm_next_situation_messages(
    action_text,
    current_session,
    user_role,
    recent_turn_history=None
):
    acting_role_brief = get_role_brief(current_session, user_role)
    other_role_brief = get_other_role_brief(current_session, user_role)
    recent_history_context = format_recent_turn_history(recent_turn_history)
    if recent_history_context == "":
        recent_history_context = "No prior turn history available."

    system_message = (
        "You are generating the next current_situation for an interpersonal role-play training simulation. "
        "Return only the next current_situation text, or a JSON object with a single next_situation field. "
        "Do not judge validity, do not give coaching advice, and do not mention the prompt or system instructions."
    )
    user_message = (
        f"Scenario title: {current_session.get('title', '')}\n"
        f"Scenario context: {current_session.get('context', '')}\n"
        f"Scenario conflict: {current_session.get('conflict', '')}\n"
        f"Current turn number: {current_session.get('current_turn', 1)}\n"
        f"Current situation: {current_session.get('current_situation', '')}\n"
        f"Acting user role: {user_role}\n"
        f"Acting user role brief: {acting_role_brief}\n"
        f"Other role brief: {other_role_brief}\n"
        f"Recent turn history:\n{recent_history_context}\n\n"
        f"Submitted action:\n{(action_text or '').strip()}\n\n"
        "Generate a new current_situation that:\n"
        "- is written in third person\n"
        "- describes what happens after the submitted action\n"
        "- stays consistent with the scenario and roles\n"
        "- preserves emotional tension\n"
        "- does not resolve the whole conflict too quickly\n"
        "- gives the other role something meaningful to respond to\n"
        "- is concise, around 3-6 sentences\n"
        "- does not include coaching advice\n"
        "- does not mention JSON, the prompt, or system instructions\n"
        "Return only the next current_situation."
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def _build_llm_joint_next_situation_messages(
    current_session,
    role_a_action,
    role_b_action,
    recent_turn_history=None,
    recent_shared_chat=None
):
    recent_history_context = format_recent_turn_history(recent_turn_history)
    if recent_history_context == "":
        recent_history_context = "No prior turn history available."

    recent_shared_chat_context = format_recent_shared_chat_history(recent_shared_chat)
    if recent_shared_chat_context == "":
        recent_shared_chat_context = "No recent shared role-play chat available."

    system_message = (
        "You are generating the next turn platform for an interpersonal role-play training simulation. "
        "Return strict JSON only. "
        "Your job is to advance the story in a realistic, emotionally coherent way based on the scenario, both submitted actions, "
        "the recent shared conversation, and each role's private pressure. "
        "Do not judge validity, do not declare a winner, do not reveal private role briefs, and do not mention the prompt or system instructions. "
        "The output must create one concrete next-stage scene, not an abstract summary of progress."
    )
    user_message = (
        f"Scenario title: {current_session.get('title', '')}\n"
        f"Scenario context: {current_session.get('context', '')}\n"
        f"Scenario conflict: {current_session.get('conflict', '')}\n"
        f"Current turn number: {current_session.get('current_turn', 1)}\n"
        f"Current situation: {current_session.get('current_situation', '')}\n"
        f"Role A brief: {current_session.get('role_a_brief', '')}\n"
        f"Role B brief: {current_session.get('role_b_brief', '')}\n"
        f"Role A action:\n{(role_a_action or '').strip()}\n\n"
        f"Role B action:\n{(role_b_action or '').strip()}\n\n"
        f"Recent turn history:\n{recent_history_context}\n\n"
        f"Recent Shared Role-play Chat:\n{recent_shared_chat_context}\n\n"
        "Before writing, infer the current state of the conflict from all of the context above. Decide whether it is:\n"
        "- escalating\n"
        "- softening\n"
        "- temporarily resolved\n"
        "- shifting into a related but new conflict\n"
        "- creating a future consequence or test\n\n"
        "Story progression rules:\n"
        "- Treat this as story progression, not just a summary of the two actions\n"
        "- Connect the next moment to the original scenario theme and the actual actions the users took\n"
        "- Use recent shared chat messages if they change tone, intent, trust, or misunderstanding\n"
        "- If the immediate conflict is easing, do not end the scenario; instead create a believable next-stage situation that tests whether the pattern has really changed\n"
        "- If the two users take repair-oriented actions, create a new related situation such as trip planning, an approaching birthday or anniversary, a reminder system, a follow-up meeting, or another realistic test of care, responsibility, or sincerity\n"
        "- The next situation may introduce a realistic follow-up moment, time jump, consequence, or related decision point\n"
        "- Do not simply reset to the original conflict wording\n"
        "- Do not make characters behave randomly or create dramatic events unless the prior actions justify it\n"
        "- Do not moralize or decide who is right\n\n"
        "Requirements for shared_situation:\n"
        "- neutral third-person narration\n"
        "- maximum 3 sentences\n"
        "- begin with a short neutral summary of what changed in the conflict\n"
        "- then set up a new shared current situation that naturally follows\n"
        "- include a concrete time, event, or upcoming moment such as next week, later that evening, an upcoming meeting, a trip plan, a birthday, a follow-up task, or another realistic scene anchor\n"
        "- include one concrete new interpersonal tension, mismatch, or uncertainty that was created by the users' actions\n"
        "- reflect both actions fairly without over-explaining feelings\n"
        "- keep the conflict emotionally nuanced and realistic\n"
        "- do not decide the next move for either participant\n"
        "- end with one clear unresolved decision point, tension point, or open question\n\n"
        "Bad shared_situation example:\n"
        "- 'Both sides have now acted, so the conflict is moving into a more defined next stage.'\n"
        "Good shared_situation example:\n"
        "- 'The anniversary conflict has eased for now. Next week, the couple starts planning the make-up trip they agreed to take, but one person notices they are doing most of the planning while the other believes agreeing to the trip already shows effort. They now have to decide how to talk about what counts as care before the trip creates a new disappointment.'\n\n"
        "Requirements for role_a_perspective and role_b_perspective:\n"
        "- one concise private-facing pressure, dilemma, or emotional stake for that role in this new stage\n"
        "- grounded in that role's brief and what just happened\n"
        "- must not reveal the other role's private brief\n\n"
        "Requirements for next_decision_point:\n"
        "- one concise shared decision point the scenario is now testing\n"
        "- it should invite the next turn instead of ending the story\n\n"
        "Requirements for updated_role_a_brief and updated_role_b_brief:\n"
        "- concise private role briefs for the new stage\n"
        "- preserve the role's identity and ongoing motivation\n"
        "- reflect the new situation, what that role privately knows, fears, assumes, or is watching for now\n"
        "- do not reveal the other role's private perspective or hidden motives\n"
        "- suitable for display as the role's current private brief in the next turn\n\n"
        "Requirements for role_a_suggestion and role_b_suggestion:\n"
        "- private coaching for that role only\n"
        "- 2 to 4 concise bullet points or short sentences\n"
        "- written in second person\n"
        "- may refer to visible actions, recent shared chat, and the shared situation\n"
        "- should surface that role's current pressure, dilemma, or what they may now need to decide next\n"
        "- must not reveal the other role's private brief\n\n"
        "Return JSON only in this exact shape:\n"
        "{\n"
        '  "shared_situation": "...",\n'
        '  "role_a_perspective": "...",\n'
        '  "role_b_perspective": "...",\n'
        '  "next_decision_point": "...",\n'
        '  "updated_role_a_brief": "...",\n'
        '  "updated_role_b_brief": "...",\n'
        '  "role_a_suggestion": "...",\n'
        '  "role_b_suggestion": "..."\n'
        "}"
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def _write_story_progression_prompt_debug_file(prompt_text):
    if str(prompt_text or "").strip() == "":
        return

    try:
        prompt_debug_path = Path(__file__).resolve().parent / "debug_last_story_progression_prompt.txt"
        prompt_debug_path.write_text(str(prompt_text), encoding="utf-8")
    except OSError:
        pass


def _extract_json_object_from_text(raw_text):
    text = (raw_text or "").strip()
    if text == "":
        raise ValueError("Empty response text.")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _normalize_turn_action_risk_flags(raw_flags):
    if raw_flags is None:
        return []

    if isinstance(raw_flags, str):
        candidate_flags = re.split(r"[,|/]", raw_flags)
    elif isinstance(raw_flags, list):
        candidate_flags = raw_flags
    else:
        candidate_flags = [raw_flags]

    normalized_flags: List[str] = []
    for flag in candidate_flags:
        normalized_flag = str(flag or "").strip()
        if normalized_flag and normalized_flag not in normalized_flags:
            normalized_flags.append(normalized_flag)
    return normalized_flags


def _normalize_turn_action_result(raw_result):
    if not isinstance(raw_result, dict):
        raise ValueError("Turn action response must be a JSON object.")

    accepted_raw = raw_result.get("accepted")
    if isinstance(accepted_raw, bool):
        accepted = accepted_raw
    elif isinstance(accepted_raw, str):
        lowered = accepted_raw.strip().lower()
        if lowered in {"true", "1", "yes"}:
            accepted = True
        elif lowered in {"false", "0", "no"}:
            accepted = False
        else:
            raise ValueError("Invalid accepted value.")
    else:
        raise ValueError("Missing accepted value.")

    reason = str(raw_result.get("reason") or "").strip()
    coach_note = str(raw_result.get("coach_note") or "").strip()
    next_situation = str(raw_result.get("next_situation") or "").strip()
    risk_flags = _normalize_turn_action_risk_flags(raw_result.get("risk_flags"))
    lowered_flags = {flag.lower() for flag in risk_flags}

    if reason == "":
        reason = coach_note
    if reason == "":
        raise ValueError("Missing reason value.")

    blocking_flags = {
        "too vague",
        "unrelated",
        "unsafe",
        "not actionable",
        "abusive",
        "threatening",
    }
    if accepted and lowered_flags.intersection(blocking_flags):
        accepted = False

    if not accepted:
        next_situation = ""
        if coach_note == "":
            coach_note = (
                "Describe one specific, relevant, and safe action the other person could realistically respond to."
            )
    elif next_situation == "":
        raise ValueError("Accepted result is missing next_situation.")

    return _build_turn_action_result(
        accepted=accepted,
        reason=reason,
        next_situation=next_situation,
        risk_flags=risk_flags,
        coach_note=coach_note,
    )


def _normalize_next_situation_response(raw_text):
    text = str(raw_text or "").strip()
    if text == "":
        raise ValueError("Empty next_situation response.")

    if text.startswith("{") or "```" in text:
        try:
            parsed = _extract_json_object_from_text(text)
            if isinstance(parsed, dict):
                next_situation = str(
                    parsed.get("next_situation")
                    or parsed.get("current_situation")
                    or ""
                ).strip()
                if next_situation != "":
                    return next_situation
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    return text


def _build_joint_turn_generation_result(
    *,
    next_situation,
    shared_situation="",
    role_a_perspective="",
    role_b_perspective="",
    next_decision_point="",
    updated_role_a_brief="",
    updated_role_b_brief="",
    role_a_suggestion,
    role_b_suggestion
):
    normalized_shared_situation = str(shared_situation or next_situation or "").strip()
    return {
        "next_situation": normalized_shared_situation,
        "shared_situation": normalized_shared_situation,
        "role_a_perspective": str(role_a_perspective or "").strip(),
        "role_b_perspective": str(role_b_perspective or "").strip(),
        "next_decision_point": str(next_decision_point or "").strip(),
        "updated_role_a_brief": str(updated_role_a_brief or "").strip(),
        "updated_role_b_brief": str(updated_role_b_brief or "").strip(),
        "role_a_suggestion": str(role_a_suggestion or "").strip(),
        "role_b_suggestion": str(role_b_suggestion or "").strip(),
    }


def _limit_to_max_sentences(text, max_sentences=3):
    normalized_text = str(text or "").strip()
    if normalized_text == "":
        return ""

    sentence_parts = re.split(r"(?<=[.!?])\s+", normalized_text)
    compact_parts = [part.strip() for part in sentence_parts if part.strip()]
    if len(compact_parts) <= max_sentences:
        return normalized_text
    return " ".join(compact_parts[:max_sentences]).strip()


def _normalize_suggestion_text(raw_value):
    if isinstance(raw_value, list):
        items = [str(item or "").strip() for item in raw_value if str(item or "").strip()]
        if not items:
            return ""
        return "\n".join(
            item if item.startswith("-") else f"- {item}"
            for item in items
        ).strip()

    return str(raw_value or "").strip()


def _contains_any_keyword(text, keywords):
    normalized_text = str(text or "").strip()
    lowered_text = normalized_text.lower()
    for keyword in keywords:
        if re.search(r"[\u4e00-\u9fff]", keyword):
            if keyword in normalized_text:
                return True
        elif keyword.lower() in lowered_text:
            return True
    return False


def _looks_abstract_story_progression_text(text):
    normalized_text = str(text or "").strip()
    lowered_text = normalized_text.lower()
    if normalized_text == "":
        return True

    abstract_phrases = [
        "moving into a more defined next stage",
        "both sides have now acted",
        "the conflict is moving",
        "the interaction moves forward",
        "the tension is more visible",
        "a more defined next stage",
    ]
    if any(phrase in lowered_text or phrase in normalized_text for phrase in abstract_phrases):
        return True

    concrete_scene_markers = [
        "later", "that evening", "the next day", "next week", "next month", "soon after",
        "at the next", "during the trip", "before the birthday", "anniversary", "birthday",
        "trip", "celebration", "dinner", "coffee", "call", "meeting", "check-in", "launch",
        "deadline", "weekend", "reminder", "message", "plan", "travel",
    ]
    tension_markers = [
        "but", "however", "while", "yet", "even though", "although", "still", "worry",
        "uncertain", "assumes", "expects", "misunderstands", "pressure", "boundary",
        "resentment", "hurt", "trust", "sincerity",
    ]

    has_scene_marker = _contains_any_keyword(normalized_text, concrete_scene_markers)
    has_tension_marker = _contains_any_keyword(normalized_text, tension_markers)
    return not (has_scene_marker and has_tension_marker)


def _validate_joint_story_progression_result(parsed_result):
    shared_situation = str((parsed_result or {}).get("shared_situation") or "").strip()
    if shared_situation == "":
        raise ValueError("Missing shared_situation.")
    if _looks_abstract_story_progression_text(shared_situation):
        raise ValueError("Abstract shared_situation.")
    return parsed_result


def _build_joint_progression_retry_messages(base_messages, previous_reply_text):
    retry_instruction = (
        "Your previous output was too abstract or generic. Rewrite it as one concrete next-stage scene. "
        "The new shared_situation must include: "
        "1. a specific time or event anchor, "
        "2. one clear new interpersonal tension, and "
        "3. a believable next decision point. "
        "Do not write abstract phrases like 'the conflict is moving into a new stage' or 'both sides have now acted'. "
        "Bad example: 'The conflict is moving into a more defined next stage.' "
        "Good example: 'The anniversary conflict has eased for now. Next week, the couple starts planning the make-up trip they agreed on, but one person notices they are doing most of the planning while the other believes agreeing to the trip already shows effort.' "
        "Return strict JSON only with shared_situation, role_a_perspective, role_b_perspective, next_decision_point, updated_role_a_brief, updated_role_b_brief, role_a_suggestion, and role_b_suggestion."
    )
    return [
        *base_messages,
        {"role": "assistant", "content": str(previous_reply_text or "").strip()},
        {"role": "user", "content": retry_instruction},
    ]


def _build_default_role_suggestion(
    current_session,
    role_name,
    own_action,
    other_action
):
    role_brief = get_role_brief(current_session, role_name).strip()
    role_focus = role_brief.split(".")[0].strip()
    own_signal = classify_action_signal(own_action or "")
    other_action_text = (other_action or "").strip()

    guidance_lines = []
    if role_focus:
        guidance_lines.append(f"- Stay grounded in your role focus: {role_focus}.")

    if other_action_text:
        guidance_lines.append(
            "- Respond directly to the other participant's latest action instead of broadening the conflict."
        )

    if own_signal == "repair":
        guidance_lines.append("- Keep your tone steady and make one clear request or question.")
    elif own_signal == "clarify":
        guidance_lines.append("- Ask one concrete follow-up question or name one specific point you want clarified.")
    elif own_signal == "escalate":
        guidance_lines.append("- Slow the pace down and choose one firm but non-threatening sentence for your next move.")
    else:
        guidance_lines.append("- Decide on one specific sentence, question, or boundary you want to put on the table next.")

    return "\n".join(guidance_lines[:3]).strip()


def _build_default_role_perspective(
    current_session,
    role_name,
    own_action,
    other_action
):
    role_brief = get_role_brief(current_session, role_name).strip()
    role_focus = role_brief.split(".")[0].strip()
    own_action_text = (own_action or "").strip()
    other_action_text = (other_action or "").strip()
    own_signal = _classify_story_progression_action_signal(own_action or "")
    other_signal = _classify_story_progression_action_signal(other_action or "")

    if role_focus and own_signal == "repair" and other_signal == "repair":
        return (
            f"You are carrying this pressure into the next stage: {role_focus}. "
            "The conflict is calmer, but now you are watching whether the softer tone becomes real follow-through."
        )
    if role_focus and other_action_text:
        return (
            f"You are carrying this pressure into the next stage: {role_focus}. "
            "What the other person just did now forces you to decide how directly you want to respond."
        )
    if role_focus:
        return f"You are still carrying this pressure into the next stage: {role_focus}."
    if own_action_text:
        return "You now need to decide whether to build on your last move or protect yourself more carefully."
    return "You now need to decide what kind of next move fits both your goals and the changed situation."


def _build_default_evolved_role_brief(
    current_session,
    role_name,
    shared_situation,
    own_action,
    other_action
):
    original_brief = get_role_brief(current_session, role_name).strip()
    role_label = "You are Role A." if role_name == "role_a" else "You are Role B."
    role_focus = original_brief.split(".")[0].strip()
    own_signal = _classify_story_progression_action_signal(own_action or "")
    other_signal = _classify_story_progression_action_signal(other_action or "")
    shared_preview = str(shared_situation or "").strip()
    if len(shared_preview) > 220:
        shared_preview = shared_preview[:217] + "..."

    lines = [role_label]
    if role_focus:
        lines.append(role_focus.rstrip(".") + ".")
    if shared_preview:
        lines.append(f"The situation has now shifted: {shared_preview}")

    if own_signal == "repair" and other_signal == "repair":
        lines.append(
            "The immediate conflict is calmer, but you are now watching whether this repair turns into real follow-through or only temporary relief."
        )
    elif own_signal == "clarify":
        lines.append(
            "You want the next exchange to produce clearer understanding, but you still need to decide how direct you can be without reopening the whole conflict."
        )
    elif own_signal == "escalate":
        lines.append(
            "You still feel pressure around the conflict, and your next move may determine whether the situation hardens or becomes easier to repair."
        )
    else:
        lines.append(
            "You now need to decide how much initiative, caution, or honesty this new stage requires from you."
        )

    return " ".join(line.strip() for line in lines if line.strip()).strip()


def _build_default_next_decision_point(role_a_action, role_b_action):
    role_a_signal = _classify_story_progression_action_signal(role_a_action or "")
    role_b_signal = _classify_story_progression_action_signal(role_b_action or "")

    if role_a_signal == "repair" and role_b_signal == "repair":
        return (
            "Both sides have softened the immediate conflict, but now need to decide whether they will turn that softer tone into a real new pattern."
        )
    if "escalate" in {role_a_signal, role_b_signal}:
        return (
            "Both sides now need to decide whether to slow the conflict down or press harder on their own position."
        )
    return (
        "Both sides now need to decide what they are willing to clarify, request, or risk in order to move the conversation forward."
    )


def _infer_joint_story_theme(current_session):
    theme_text = " ".join(
        str(current_session.get(key) or "")
        for key in ("title", "context", "conflict", "current_situation", "role_a_brief", "role_b_brief")
    ).strip()
    lowered_theme = theme_text.lower()

    if any(keyword in lowered_theme for keyword in ["anniversary", "birthday", "date", "celebrat", "trip", "reminder", "important day"]):
        return "important_dates"
    if any(keyword in lowered_theme for keyword in ["manager", "employee", "teammate", "team member", "deadline", "launch", "project", "support", "performance"]):
        return "workplace"
    if any(keyword in lowered_theme for keyword in ["partner", "couple", "relationship", "boyfriend", "girlfriend"]):
        return "relationship"
    return "general"


def _build_default_joint_turn_result(
    current_session,
    role_a_action,
    role_b_action
):
    shared_situation = _generate_next_situation_from_joint_actions_local(
        current_session=current_session,
        role_a_action=role_a_action,
        role_b_action=role_b_action
    )
    role_a_perspective = _build_default_role_perspective(
        current_session=current_session,
        role_name="role_a",
        own_action=role_a_action,
        other_action=role_b_action
    )
    role_b_perspective = _build_default_role_perspective(
        current_session=current_session,
        role_name="role_b",
        own_action=role_b_action,
        other_action=role_a_action
    )
    next_decision_point = _build_default_next_decision_point(role_a_action, role_b_action)
    updated_role_a_brief = _build_default_evolved_role_brief(
        current_session=current_session,
        role_name="role_a",
        shared_situation=shared_situation,
        own_action=role_a_action,
        other_action=role_b_action
    )
    updated_role_b_brief = _build_default_evolved_role_brief(
        current_session=current_session,
        role_name="role_b",
        shared_situation=shared_situation,
        own_action=role_b_action,
        other_action=role_a_action
    )
    role_a_suggestion = _build_default_role_suggestion(
        current_session=current_session,
        role_name="role_a",
        own_action=role_a_action,
        other_action=role_b_action
    )
    role_b_suggestion = _build_default_role_suggestion(
        current_session=current_session,
        role_name="role_b",
        own_action=role_b_action,
        other_action=role_a_action
    )
    return _build_joint_turn_generation_result(
        next_situation=shared_situation,
        shared_situation=shared_situation,
        role_a_perspective=role_a_perspective,
        role_b_perspective=role_b_perspective,
        next_decision_point=next_decision_point,
        updated_role_a_brief=updated_role_a_brief,
        updated_role_b_brief=updated_role_b_brief,
        role_a_suggestion=role_a_suggestion,
        role_b_suggestion=role_b_suggestion
    )


def _normalize_joint_turn_generation_result(raw_result, fallback_result):
    if not isinstance(raw_result, dict):
        raise ValueError("Joint turn result must be a JSON object.")

    shared_situation = _limit_to_max_sentences(
        str(raw_result.get("shared_situation") or raw_result.get("next_situation") or "").strip(),
        max_sentences=3
    )
    if shared_situation == "":
        raise ValueError("Missing shared_situation.")

    role_a_perspective = str(
        raw_result.get("role_a_perspective")
        or fallback_result.get("role_a_perspective")
        or ""
    ).strip()
    role_b_perspective = str(
        raw_result.get("role_b_perspective")
        or fallback_result.get("role_b_perspective")
        or ""
    ).strip()
    next_decision_point = str(
        raw_result.get("next_decision_point")
        or fallback_result.get("next_decision_point")
        or ""
    ).strip()
    updated_role_a_brief = str(
        raw_result.get("updated_role_a_brief")
        or raw_result.get("role_a_brief")
        or fallback_result.get("updated_role_a_brief")
        or fallback_result.get("role_a_brief")
        or ""
    ).strip()
    updated_role_b_brief = str(
        raw_result.get("updated_role_b_brief")
        or raw_result.get("role_b_brief")
        or fallback_result.get("updated_role_b_brief")
        or fallback_result.get("role_b_brief")
        or ""
    ).strip()

    role_a_suggestion = _normalize_suggestion_text(raw_result.get("role_a_suggestion"))
    role_b_suggestion = _normalize_suggestion_text(raw_result.get("role_b_suggestion"))

    if role_a_suggestion == "":
        role_a_suggestion = fallback_result["role_a_suggestion"]
    if role_b_suggestion == "":
        role_b_suggestion = fallback_result["role_b_suggestion"]

    return _build_joint_turn_generation_result(
        next_situation=shared_situation,
        shared_situation=shared_situation,
        role_a_perspective=role_a_perspective,
        role_b_perspective=role_b_perspective,
        next_decision_point=next_decision_point,
        updated_role_a_brief=updated_role_a_brief,
        updated_role_b_brief=updated_role_b_brief,
        role_a_suggestion=role_a_suggestion,
        role_b_suggestion=role_b_suggestion
    )


def _extract_chat_completion_result(response_data):
    result = {
        "text": "",
        "reply_extracted": False,
        "content_type": "missing",
        "choice_count": 0,
        "has_reasoning_content": False,
        "reasoning_length": 0,
    }

    choices = response_data.get("choices") or []
    result["choice_count"] = len(choices)
    if not choices:
        output_text = response_data.get("output_text", "")
        if isinstance(output_text, str) and output_text.strip() != "":
            result["text"] = output_text.strip()
            result["reply_extracted"] = True
            result["content_type"] = "output_text"
        return result

    first_choice = choices[0] or {}
    message = first_choice.get("message") or {}
    content = message.get("content", "")
    reasoning_content = message.get("reasoning_content", "")
    if isinstance(reasoning_content, str) and reasoning_content.strip() != "":
        result["has_reasoning_content"] = True
        result["reasoning_length"] = len(reasoning_content.strip())

    if isinstance(content, str):
        result["text"] = content.strip()
        result["reply_extracted"] = result["text"] != ""
        result["content_type"] = "string"
        if result["reply_extracted"]:
            return result

    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                text_value = item.get("text") or item.get("content") or ""
                if text_value:
                    text_parts.append(str(text_value))
        result["text"] = "".join(text_parts).strip()
        result["reply_extracted"] = result["text"] != ""
        result["content_type"] = "list"
        if result["reply_extracted"]:
            return result

    if content is None:
        result["content_type"] = "null"
    elif isinstance(content, dict):
        result["content_type"] = "dict"
        text_value = content.get("text") or content.get("content") or ""
        result["text"] = str(text_value).strip()
        result["reply_extracted"] = result["text"] != ""
        if result["reply_extracted"]:
            return result
    elif result["content_type"] == "missing":
        result["content_type"] = type(content).__name__

    choice_text = first_choice.get("text", "")
    if isinstance(choice_text, str) and choice_text.strip() != "":
        result["text"] = choice_text.strip()
        result["reply_extracted"] = True
        result["content_type"] = "choice_text"
        return result

    output_text = response_data.get("output_text", "")
    if isinstance(output_text, str) and output_text.strip() != "":
        result["text"] = output_text.strip()
        result["reply_extracted"] = True
        result["content_type"] = "output_text"
        return result

    if content not in ("", None):
        result["text"] = str(content).strip()
        result["reply_extracted"] = result["text"] != ""

    return result


def _generate_next_situation_local(current_session, user_role, action_text):
    signal = classify_action_signal(action_text)
    actor_label = get_role_label(user_role)
    other_label = "the team member" if user_role == "role_a" else "the manager"
    current_turn = current_session["current_turn"]
    current_situation = current_session["current_situation"]
    conflict = current_session["conflict"]

    if signal == "repair":
        shift = f"{other_label} becomes slightly less guarded, but now pays close attention to whether the tone change is genuine and sustainable."
    elif signal == "clarify":
        shift = f"The conversation becomes more specific, and {other_label} starts reacting to concrete requests instead of only reacting to tone."
    elif signal == "escalate":
        shift = f"The pressure rises, and {other_label} becomes more defensive while also feeling forced to respond more directly."
    else:
        shift = f"The interaction moves forward, but {other_label} is still uncertain about the real intent behind the move."

    return (
        f"Turn {current_turn + 1} begins. After {actor_label} chooses to {action_text.strip()}, "
        f"the situation evolves from this moment: {current_situation} {shift} "
        f"The underlying tension is still: {conflict}"
    )


def _generate_next_situation_from_joint_actions_local(
    current_session,
    role_a_action,
    role_b_action,
    recent_turn_history=None
):
    role_a_signal = _classify_story_progression_action_signal(role_a_action)
    role_b_signal = _classify_story_progression_action_signal(role_b_action)
    combined_signals = {role_a_signal, role_b_signal}
    theme = _infer_joint_story_theme(current_session)

    if theme == "important_dates":
        if role_a_signal == "repair" and role_b_signal == "repair":
            return (
                "The immediate date-related conflict has eased for now. Next week, the two of them start planning the make-up celebration or trip they agreed on, but one person notices they are doing more of the emotional planning while the other believes agreeing to the plan already shows care. They now have to decide how to talk about what counts as real effort before the new plan creates fresh hurt."
            )
        if "clarify" in combined_signals or "repair" in combined_signals:
            return (
                "The tension is lower than before, but the issue has shifted into a new test. As another birthday, anniversary, or reminder-related moment approaches, one person wants a clearer system while the other worries that too much planning will make care feel less sincere. They now have to decide whether practical reminders will build trust or quietly create new resentment."
            )
        if "escalate" in combined_signals:
            return (
                "The argument about important dates is sharper now. A new celebration-related moment is approaching, and both of them are already anticipating disappointment in different ways before it even arrives. They now have to decide whether to name those expectations directly or risk turning the next event into another test."
            )

    if theme == "workplace":
        if role_a_signal == "repair" and role_b_signal == "repair":
            return (
                "The immediate workplace tension has eased for now. At the next check-in, both sides discover that support has been offered, but the real question is whether expectations, ownership, and follow-through have actually become clearer. They now have to decide whether to talk directly about accountability before the next deadline exposes the same pattern again."
            )
        if "clarify" in combined_signals or "repair" in combined_signals:
            return (
                "The conversation has become more practical, but that creates a new test instead of ending the problem. A follow-up task or deadline now forces both sides to see whether clearer communication will actually change the working pattern, or whether one side will still feel unsupported while the other feels unfairly pressured. They now have to decide what needs to be made explicit before the next milestone."
            )
        if "escalate" in combined_signals:
            return (
                "The workplace conflict has become sharper, not simpler. The next meeting now carries extra pressure because the original issue is mixing with questions about trust, tone, and responsibility under strain. They now have to decide whether to slow the conflict down or press harder on accountability."
            )

    if theme == "relationship":
        if role_a_signal == "repair" and role_b_signal == "repair":
            return (
                "The immediate conflict is softer for now, but the relationship is being tested in a new way. A few days later, a small but meaningful moment of care comes up, and one person sees it as a chance to rebuild trust while the other assumes the earlier repair was already enough. They now have to decide how to show care without turning the relationship into a quiet scorecard."
            )
        if "clarify" in combined_signals or "repair" in combined_signals:
            return (
                "The argument has not disappeared; it has shifted into a more specific question. After the recent conversation, a new moment asks both people whether they will actually communicate expectations more clearly or fall back into guessing each other's intentions. They now have to decide what to say before a small misunderstanding hardens into a bigger emotional pattern."
            )
        if "escalate" in combined_signals:
            return (
                "The relationship tension is sharper now, and the next interaction already carries the weight of this unfinished conflict. Soon after, one person hesitates before reaching out again, while the other reads that hesitation in the worst possible light. They now have to decide whether to repair the tone first or keep arguing about the original issue."
            )

    if role_a_signal == "repair" and role_b_signal == "repair":
        return (
            "The immediate conflict has eased for now, but that creates a new test instead of a clean ending. A few days later, a related follow-up moment exposes a mismatch between what one person sees as real effort and what the other sees as enough repair. They now have to decide how directly to name that mismatch before it quietly becomes resentment again."
        )
    if "clarify" in combined_signals or "repair" in combined_signals:
        return (
            "The conversation is more open than before, but it is now moving into a concrete follow-up situation rather than simply calming down. Soon after, a practical next step forces both sides to test whether clearer words will turn into shared understanding or expose a new disagreement about expectations. They now have to decide what to make explicit before the next misunderstanding takes shape."
        )
    if "escalate" in combined_signals:
        return (
            "The conflict is sharper now, and the next interaction is no longer neutral. A follow-up moment arrives sooner than either person wants, and both of them feel pressure to protect their own position before the other side defines the situation first. They now have to decide whether to slow the pace down or harden the conflict further."
        )

    return (
        "The last exchange has changed the situation, but not by ending the conflict. Soon after, a related moment forces both sides to test whether this conversation actually changed the pattern between them or only paused the discomfort. They now have to decide what expectation, request, or boundary needs to be made clear before the next misunderstanding becomes harder to repair."
    )


class LocalDeterministicAIProvider(AIProvider):
    def build_turn_coach_prompt(
        self,
        current_session,
        user_role,
        user_profile=None,
        recent_turn_history=None
    ):
        return _build_turn_coach_prompt_local(
            current_session=current_session,
            user_role=user_role,
            user_profile=user_profile,
            recent_turn_history=recent_turn_history
        )

    def validate_turn_action(self, action_text, current_session, user_role):
        return _validate_turn_action_local(
            action_text=action_text,
            current_session=current_session,
            user_role=user_role
        )

    def evaluate_turn_action(
        self,
        action_text,
        current_session,
        user_role,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        return _evaluate_turn_action_local(
            action_text=action_text,
            current_session=current_session,
            user_role=user_role,
            recent_turn_history=recent_turn_history
        )

    def generate_dynamic_ai_feedback(
        self,
        user_role,
        user_text,
        current_turn,
        current_situation,
        current_session=None,
        user_profile=None,
        recent_turn_history=None,
        recent_coach_history=None,
        debug_trace_id=None
    ):
        selection_debug = _build_provider_selection_debug_fields(_active_config)
        _log_provider_event(
            "provider_selected",
            debug_trace_id=debug_trace_id,
            **selection_debug,
            provider_stage="local_completed",
            rag_enabled=False,
            retrieved_doc_count=0
        )
        feedback = _generate_dynamic_ai_feedback_local(
            user_role=user_role,
            user_text=user_text,
            current_turn=current_turn,
            current_situation=current_situation,
            current_session=current_session,
            user_profile=user_profile,
            recent_turn_history=recent_turn_history
        )
        _set_last_ai_debug_info(
            provider="local",
            provider_stage="local_completed",
            **selection_debug,
            llm_call_attempted=False,
            llm_call_succeeded=False,
            llm_http_status=None,
            reply_extracted=(feedback or "").strip() != "",
            reply_length=len((feedback or "").strip()),
            reply_preview=_short_debug_text(feedback),
            content_type="local_string",
            rag_enabled=False,
            retrieved_doc_count=0,
            retrieved_doc_preview="",
            used_fallback=False,
            fallback_reason="",
            exception_type="",
            exception_message="",
        )
        return feedback

    def generate_next_situation(
        self,
        current_session,
        user_role,
        action_text,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        return _generate_next_situation_local(
            current_session=current_session,
            user_role=user_role,
            action_text=action_text
        )

    def generate_next_situation_from_joint_actions(
        self,
        current_session,
        role_a_action,
        role_b_action,
        recent_turn_history=None,
        recent_shared_chat=None,
        debug_trace_id=None
    ):
        selection_debug = _build_provider_selection_debug_fields(_active_config)
        fallback_result = _build_default_joint_turn_result(
            current_session=current_session,
            role_a_action=role_a_action,
            role_b_action=role_b_action
        )
        _log_provider_event(
            "story_progression_generation_started",
            debug_trace_id=debug_trace_id,
            session_id=current_session.get("id"),
            previous_turn_index=current_session.get("current_turn"),
            new_turn_index=(current_session.get("current_turn") or 1) + 1,
            role_a_action_preview=_short_debug_text(role_a_action, 160),
            role_b_action_preview=_short_debug_text(role_b_action, 160),
            shared_chat_message_count=len(recent_shared_chat or []),
            progression_history_count=len(recent_turn_history or []),
            **selection_debug,
            provider_stage="local_provider_selected"
        )
        _log_provider_event(
            "story_progression_generation_failed",
            debug_trace_id=debug_trace_id,
            session_id=current_session.get("id"),
            previous_turn_index=current_session.get("current_turn"),
            new_turn_index=(current_session.get("current_turn") or 1) + 1,
            fallback_reason="provider_not_selected",
            provider_stage="local_provider_selected",
            **selection_debug
        )
        _log_provider_event(
            "story_progression_fallback_used",
            debug_trace_id=debug_trace_id,
            session_id=current_session.get("id"),
            previous_turn_index=current_session.get("current_turn"),
            new_turn_index=(current_session.get("current_turn") or 1) + 1,
            fallback_reason="provider_not_selected",
            provider_stage="local_provider_selected",
            fallback_shared_situation_preview=_short_debug_text(fallback_result["shared_situation"], 240),
            **selection_debug
        )
        return fallback_result


class DeepSeekOpenAICompatibleProvider(AIProvider):
    """DeepSeek-backed OpenAI-compatible provider for coach feedback and turn actions."""

    def __init__(self, fallback_provider: AIProvider, config: AIEngineConfig):
        self.fallback_provider = fallback_provider
        self.config = config

    def _perform_chat_completion_request(self, endpoint, request_body, headers, timeout_seconds):
        parsed_endpoint = urlsplit(endpoint)
        if parsed_endpoint.scheme not in ("https", "http"):
            raise ValueError(f"Unsupported API base scheme: {parsed_endpoint.scheme}")

        path = parsed_endpoint.path or "/"
        if parsed_endpoint.query:
            path = f"{path}?{parsed_endpoint.query}"

        connection_class = (
            http.client.HTTPSConnection
            if parsed_endpoint.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_class(parsed_endpoint.netloc, timeout=timeout_seconds)
        started_at = time.monotonic()

        try:
            connection.request(
                "POST",
                path,
                body=request_body,
                headers=headers
            )
            response = connection.getresponse()
            response_body = response.read().decode("utf-8")
            elapsed_seconds = time.monotonic() - started_at
            if response.status >= 500:
                mark_uncertain()
            return response.status, response_body, elapsed_seconds
        except Exception:
            mark_uncertain()
            raise
        finally:
            connection.close()

    def build_turn_coach_prompt(
        self,
        current_session,
        user_role,
        user_profile=None,
        recent_turn_history=None
    ):
        return self.fallback_provider.build_turn_coach_prompt(
            current_session=current_session,
            user_role=user_role,
            user_profile=user_profile,
            recent_turn_history=recent_turn_history
        )

    def validate_turn_action(self, action_text, current_session, user_role):
        return self.fallback_provider.validate_turn_action(
            action_text=action_text,
            current_session=current_session,
            user_role=user_role
        )

    def evaluate_turn_action(
        self,
        action_text,
        current_session,
        user_role,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        fallback_result = self.fallback_provider.evaluate_turn_action(
            action_text=action_text,
            current_session=current_session,
            user_role=user_role,
            recent_turn_history=recent_turn_history,
            debug_trace_id=debug_trace_id
        )
        api_key = self.config.resolved_llm_api_key()
        if api_key == "":
            return fallback_result

        endpoint = f"{self.config.resolved_llm_api_base()}/chat/completions"
        timeout_seconds = self.config.resolved_llm_timeout_seconds()
        payload = {
            "model": self.config.resolved_llm_model(),
            "messages": _build_llm_turn_action_messages(
                action_text=action_text,
                current_session=current_session,
                user_role=user_role,
                recent_turn_history=recent_turn_history
            ),
            "stream": False
        }
        request_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        _log_provider_event(
            "submit_turn_action_provider_call_started",
            debug_trace_id=debug_trace_id,
            model=self.config.resolved_llm_model(),
            api_base=self.config.resolved_llm_api_base(),
            timeout_seconds=timeout_seconds
        )

        try:
            http_status, response_body, elapsed_seconds = self._perform_chat_completion_request(
                endpoint=endpoint,
                request_body=request_body,
                headers=headers,
                timeout_seconds=timeout_seconds
            )
            extraction = _extract_chat_completion_result(json.loads(response_body))
            _log_provider_event(
                "submit_turn_action_provider_call_completed",
                debug_trace_id=debug_trace_id,
                http_status=http_status,
                elapsed_seconds=round(elapsed_seconds, 3),
                reply_extracted=extraction["reply_extracted"],
                content_type=extraction["content_type"],
                raw_reply_preview=_short_debug_text(extraction["text"], 240)
            )

            if not extraction["reply_extracted"]:
                return fallback_result

            try:
                parsed_result = _extract_json_object_from_text(extraction["text"])
                return _normalize_turn_action_result(parsed_result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                _log_provider_event(
                    "submit_turn_action_json_parse_failed",
                    debug_trace_id=debug_trace_id,
                    exception_type=type(exc).__name__,
                    exception_message=str(exc),
                    raw_reply_preview=_short_debug_text(extraction["text"], 240)
                )
                return fallback_result
        except (
            error.HTTPError,
            error.URLError,
            http.client.HTTPException,
            socket.timeout,
            TimeoutError,
            ValueError,
            KeyError,
            IndexError,
            json.JSONDecodeError
        ) as exc:
            _log_provider_event(
                "submit_turn_action_provider_call_completed",
                debug_trace_id=debug_trace_id,
                used_fallback=True,
                fallback_reason=type(exc).__name__,
                exception_message=str(exc)
            )
            return fallback_result

    def generate_dynamic_ai_feedback(
        self,
        user_role,
        user_text,
        current_turn,
        current_situation,
        current_session=None,
        user_profile=None,
        recent_turn_history=None,
        recent_coach_history=None,
        debug_trace_id=None
    ):
        selection_debug = _build_provider_selection_debug_fields(self.config)
        fallback_feedback_cache = {"value": None}
        timeout_seconds = max(self.config.resolved_llm_timeout_seconds(), 60.0)
        debug_info = {
            "provider": "llm",
            "provider_stage": "entering_provider",
            **selection_debug,
            "llm_call_attempted": True,
            "llm_call_succeeded": False,
            "llm_http_status": None,
            "reply_extracted": False,
            "reply_length": 0,
            "reply_preview": "",
            "content_type": "missing",
            "rag_enabled": False,
            "retrieved_doc_count": 0,
            "retrieved_doc_preview": "",
            "used_fallback": True,
            "fallback_reason": "",
            "response_choice_count": 0,
            "has_reasoning_content": False,
            "reasoning_length": 0,
            "fallback_reply_length": 0,
            "fallback_reply_preview": "",
            "llm_model": self.config.resolved_llm_model(),
            "llm_api_base": self.config.resolved_llm_api_base(),
            "llm_timeout_seconds": timeout_seconds,
            "pipeline_error": "",
            "exception_type": "",
            "exception_message": "",
        }

        def sync_debug(stage=None, **updates):
            if stage is not None:
                debug_info["provider_stage"] = stage
            debug_info.update(updates)
            _set_last_ai_debug_info(**debug_info)

        def get_fallback_feedback():
            if fallback_feedback_cache["value"] is None:
                fallback_feedback_cache["value"] = _generate_dynamic_ai_feedback_local(
                    user_role=user_role,
                    user_text=user_text,
                    current_turn=current_turn,
                    current_situation=current_situation,
                    current_session=current_session,
                    user_profile=user_profile,
                    recent_turn_history=recent_turn_history
                )
            return fallback_feedback_cache["value"]

        def start_fallback(reason, pipeline_error, event_fields=None, exception=None):
            fallback_feedback = get_fallback_feedback()
            debug_info["fallback_reason"] = reason
            debug_info["pipeline_error"] = pipeline_error
            debug_info["exception_type"] = type(exception).__name__ if exception is not None else ""
            debug_info["exception_message"] = str(exception) if exception is not None else ""
            debug_info["fallback_reply_length"] = len((fallback_feedback or "").strip())
            debug_info["fallback_reply_preview"] = _short_debug_text(fallback_feedback)
            sync_debug("fallback_started")
            _log_provider_event(
                "fallback_started",
                debug_trace_id=debug_trace_id,
                fallback_reason=reason,
                pipeline_error=pipeline_error,
                exception_type=debug_info["exception_type"] or None,
                exception_message=debug_info["exception_message"] or None,
                **(event_fields or {})
            )
            sync_debug("fallback_completed")
            _log_provider_event(
                "fallback_completed",
                debug_trace_id=debug_trace_id,
                fallback_reason=reason,
                fallback_reply_length=len((fallback_feedback or "").strip()),
                provider_stage=debug_info["provider_stage"],
                exception_type=debug_info["exception_type"] or None,
                exception_message=debug_info["exception_message"] or None
            )
            return fallback_feedback

        sync_debug("entering_provider")
        _log_provider_event(
            "provider_selected",
            debug_trace_id=debug_trace_id,
            **selection_debug,
            provider_stage=debug_info["provider_stage"],
            rag_enabled=False,
            retrieved_doc_count=0
        )
        _log_provider_event(
            "entering_provider",
            debug_trace_id=debug_trace_id,
            model=debug_info["llm_model"],
            api_base=debug_info["llm_api_base"],
            timeout_seconds=timeout_seconds
        )

        api_key = self.config.resolved_llm_api_key()
        if api_key == "":
            return start_fallback(
                reason="missing_api_key",
                pipeline_error="Missing DeepSeek API key."
            )

        coach_prompt_bundle = _build_llm_coach_feedback_messages(
            current_session=current_session or {},
            user_role=user_role,
            user_text=user_text,
            current_turn=current_turn,
            current_situation=current_situation,
            private_role_brief=get_role_brief(current_session or {}, user_role),
            user_profile=user_profile,
            recent_turn_history=recent_turn_history,
            recent_coach_history=recent_coach_history,
            debug_trace_id=debug_trace_id
        )
        sync_debug(
            "prompt_built",
            rag_enabled=bool(coach_prompt_bundle.get("rag_enabled")),
            retrieved_doc_count=int(coach_prompt_bundle.get("retrieved_doc_count", 0)),
            retrieved_doc_preview=str(coach_prompt_bundle.get("rag_preview") or "")
        )
        payload = {
            "model": self.config.resolved_llm_model(),
            "messages": coach_prompt_bundle["messages"],
            "stream": False
        }

        endpoint = f"{self.config.resolved_llm_api_base()}/chat/completions"
        request_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        sync_debug("before_http_request")
        if _is_truthy_env_flag(os.getenv("ECHOROLE_DEBUG_PROMPT")):
            prompt_text = str(coach_prompt_bundle.get("prompt_text") or "")
            _log_provider_event(
                "ai_coach_deepseek_prompt_built",
                debug_trace_id=debug_trace_id,
                prompt_length=len(prompt_text),
                profile_included=bool(coach_prompt_bundle.get("profile_included")),
                rag_note_count=coach_prompt_bundle.get("rag_note_count", 0),
                retrieved_doc_count=coach_prompt_bundle.get("retrieved_doc_count", 0),
                ai_coach_history_message_count=coach_prompt_bundle.get(
                    "ai_coach_history_message_count",
                    0
                ),
                first_coach_reply=coach_prompt_bundle.get(
                    "first_coach_reply",
                    False
                ),
                ai_coach_prompt_mode=coach_prompt_bundle.get(
                    "ai_coach_prompt_mode",
                    "unknown"
                ),
                latest_user_language=coach_prompt_bundle.get(
                    "latest_user_language",
                    "unknown"
                ),
                rag_enabled=coach_prompt_bundle.get("rag_enabled", False),
                prompt_preview=_short_debug_text(prompt_text, 1000)
            )
            try:
                prompt_debug_path = Path(__file__).resolve().parent / "debug_last_ai_coach_prompt.txt"
                prompt_debug_path.write_text(prompt_text, encoding="utf-8")
            except OSError:
                pass
        _log_provider_event(
            "before_http_request",
            debug_trace_id=debug_trace_id,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds
        )
        try:
            http_status, response_body, elapsed_seconds = self._perform_chat_completion_request(
                endpoint=endpoint,
                request_body=request_body,
                headers=headers,
                timeout_seconds=timeout_seconds
            )
            debug_info["llm_call_succeeded"] = True
            debug_info["llm_http_status"] = http_status
            sync_debug("after_http_response")
            _log_provider_event(
                "after_http_response",
                debug_trace_id=debug_trace_id,
                http_status=http_status,
                elapsed_seconds=round(elapsed_seconds, 3),
                response_length=len(response_body)
            )
            sync_debug("parsing_response")
            _log_provider_event(
                "parsing_response",
                debug_trace_id=debug_trace_id,
                http_status=http_status
            )
            extraction = _extract_chat_completion_result(json.loads(response_body))
            debug_info["reply_extracted"] = extraction["reply_extracted"]
            debug_info["reply_length"] = len(extraction["text"])
            debug_info["reply_preview"] = _short_debug_text(extraction["text"])
            debug_info["content_type"] = extraction["content_type"]
            debug_info["response_choice_count"] = extraction["choice_count"]
            debug_info["has_reasoning_content"] = extraction["has_reasoning_content"]
            debug_info["reasoning_length"] = extraction["reasoning_length"]

            if extraction["reply_extracted"]:
                debug_info["used_fallback"] = False
                debug_info["pipeline_error"] = ""
                sync_debug("completed")
                _log_provider_event(
                    "completed",
                    debug_trace_id=debug_trace_id,
                    http_status=http_status,
                    reply_length=debug_info["reply_length"],
                    content_type=debug_info["content_type"]
                )
                return extraction["text"]

            return start_fallback(
                reason="empty_llm_reply",
                pipeline_error="DeepSeek returned an empty coach reply.",
                event_fields={
                    "http_status": http_status,
                    "content_type": debug_info["content_type"]
                },
                exception=None
            )
        except (
            error.HTTPError,
            error.URLError,
            http.client.HTTPException,
            socket.timeout,
            TimeoutError,
            ValueError,
            KeyError,
            IndexError,
            json.JSONDecodeError
        ) as exc:
            if isinstance(exc, error.HTTPError):
                return start_fallback(
                    reason="http_error",
                    pipeline_error=f"DeepSeek HTTP error: {exc.code}",
                    event_fields={"http_status": exc.code},
                    exception=exc
                )
            elif isinstance(exc, error.URLError):
                reason_text = str(exc.reason).lower()
                if "timed out" in reason_text or "timeout" in reason_text:
                    return start_fallback(
                        reason="http_timeout",
                        pipeline_error=(
                            f"DeepSeek request timed out after {timeout_seconds:.1f} seconds."
                        ),
                        event_fields={"network_reason": str(exc.reason)},
                        exception=exc
                    )
                else:
                    return start_fallback(
                        reason="network_error",
                        pipeline_error=f"DeepSeek network error: {exc.reason}",
                        event_fields={"network_reason": str(exc.reason)},
                        exception=exc
                    )
            elif isinstance(exc, socket.timeout):
                return start_fallback(
                    reason="http_timeout",
                    pipeline_error=(
                        f"DeepSeek request timed out after {timeout_seconds:.1f} seconds."
                    ),
                    exception=exc
                )
            elif isinstance(exc, json.JSONDecodeError):
                return start_fallback(
                    reason="invalid_json",
                    pipeline_error="DeepSeek returned invalid JSON.",
                    exception=exc
                )
            elif isinstance(exc, http.client.HTTPException):
                return start_fallback(
                    reason="http_exception",
                    pipeline_error=f"DeepSeek HTTP client error: {exc}",
                    exception=exc
                )
            elif isinstance(exc, TimeoutError):
                return start_fallback(
                    reason="http_timeout",
                    pipeline_error=(
                        f"DeepSeek request timed out after {timeout_seconds:.1f} seconds."
                    ),
                    exception=exc
                )
            else:
                return start_fallback(
                    reason="llm_exception",
                    pipeline_error=str(exc),
                    exception=exc
                )

    def generate_next_situation(
        self,
        current_session,
        user_role,
        action_text,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        fallback_next_situation = self.fallback_provider.generate_next_situation(
            current_session=current_session,
            user_role=user_role,
            action_text=action_text,
            recent_turn_history=recent_turn_history,
            debug_trace_id=debug_trace_id
        )
        api_key = self.config.resolved_llm_api_key()
        if api_key == "":
            _log_provider_event(
                "submit_turn_action_llm_generation_failed_using_fallback",
                debug_trace_id=debug_trace_id,
                fallback_reason="missing_api_key"
            )
            return fallback_next_situation

        endpoint = f"{self.config.resolved_llm_api_base()}/chat/completions"
        timeout_seconds = self.config.resolved_llm_timeout_seconds()
        payload = {
            "model": self.config.resolved_llm_model(),
            "messages": _build_llm_next_situation_messages(
                action_text=action_text,
                current_session=current_session,
                user_role=user_role,
                recent_turn_history=recent_turn_history
            ),
            "stream": False
        }
        request_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        _log_provider_event(
            "submit_turn_action_llm_generation_started",
            debug_trace_id=debug_trace_id,
            model=self.config.resolved_llm_model(),
            api_base=self.config.resolved_llm_api_base(),
            timeout_seconds=timeout_seconds
        )

        try:
            http_status, response_body, elapsed_seconds = self._perform_chat_completion_request(
                endpoint=endpoint,
                request_body=request_body,
                headers=headers,
                timeout_seconds=timeout_seconds
            )
            extraction = _extract_chat_completion_result(json.loads(response_body))
            if not extraction["reply_extracted"]:
                _log_provider_event(
                    "submit_turn_action_llm_generation_failed_using_fallback",
                    debug_trace_id=debug_trace_id,
                    fallback_reason="empty_llm_reply",
                    http_status=http_status
                )
                return fallback_next_situation

            next_situation = _normalize_next_situation_response(extraction["text"])
            _log_provider_event(
                "submit_turn_action_llm_generation_completed",
                debug_trace_id=debug_trace_id,
                http_status=http_status,
                elapsed_seconds=round(elapsed_seconds, 3),
                next_situation_preview=_short_debug_text(next_situation, 240)
            )
            return next_situation
        except (
            error.HTTPError,
            error.URLError,
            http.client.HTTPException,
            socket.timeout,
            TimeoutError,
            ValueError,
            KeyError,
            IndexError,
            json.JSONDecodeError
        ) as exc:
            _log_provider_event(
                "submit_turn_action_llm_generation_failed_using_fallback",
                debug_trace_id=debug_trace_id,
                fallback_reason=type(exc).__name__,
                exception_message=str(exc)
            )
            return fallback_next_situation

    def generate_next_situation_from_joint_actions(
        self,
        current_session,
        role_a_action,
        role_b_action,
        recent_turn_history=None,
        recent_shared_chat=None,
        debug_trace_id=None
    ):
        selection_debug = _build_provider_selection_debug_fields(self.config)
        fallback_result = self.fallback_provider.generate_next_situation_from_joint_actions(
            current_session=current_session,
            role_a_action=role_a_action,
            role_b_action=role_b_action,
            recent_turn_history=recent_turn_history,
            recent_shared_chat=recent_shared_chat,
            debug_trace_id=debug_trace_id
        )
        api_key = self.config.resolved_llm_api_key()
        if api_key == "":
            _log_provider_event(
                "story_progression_generation_failed",
                debug_trace_id=debug_trace_id,
                session_id=current_session.get("id"),
                previous_turn_index=current_session.get("current_turn"),
                new_turn_index=(current_session.get("current_turn") or 1) + 1,
                fallback_reason="llm_call_failed",
                failure_detail="missing_api_key",
                provider_stage="missing_api_key",
                **selection_debug
            )
            _log_provider_event(
                "story_progression_fallback_used",
                debug_trace_id=debug_trace_id,
                session_id=current_session.get("id"),
                previous_turn_index=current_session.get("current_turn"),
                new_turn_index=(current_session.get("current_turn") or 1) + 1,
                fallback_reason="llm_call_failed",
                failure_detail="missing_api_key",
                provider_stage="missing_api_key",
                fallback_shared_situation_preview=_short_debug_text(fallback_result["shared_situation"], 240),
                **selection_debug
            )
            return fallback_result

        endpoint = f"{self.config.resolved_llm_api_base()}/chat/completions"
        timeout_seconds = max(self.config.resolved_llm_timeout_seconds(), 60.0)
        base_messages = _build_llm_joint_next_situation_messages(
            current_session=current_session,
            role_a_action=role_a_action,
            role_b_action=role_b_action,
            recent_turn_history=recent_turn_history,
            recent_shared_chat=recent_shared_chat
        )
        prompt_text = format_messages_as_prompt_text(base_messages)
        payload = {
            "model": self.config.resolved_llm_model(),
            "messages": base_messages,
            "stream": False
        }
        request_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        def use_fallback(reason, *, failure_detail="", provider_stage="", exception=None, raw_reply_preview="", http_status=None):
            _log_provider_event(
                "story_progression_generation_failed",
                debug_trace_id=debug_trace_id,
                session_id=current_session.get("id"),
                previous_turn_index=current_session.get("current_turn"),
                new_turn_index=(current_session.get("current_turn") or 1) + 1,
                fallback_reason=reason,
                failure_detail=failure_detail,
                provider_stage=provider_stage,
                exception_type=(type(exception).__name__ if exception is not None else ""),
                exception_message=(str(exception) if exception is not None else ""),
                http_status=http_status,
                raw_reply_preview=raw_reply_preview,
                **selection_debug
            )
            _log_provider_event(
                "story_progression_fallback_used",
                debug_trace_id=debug_trace_id,
                session_id=current_session.get("id"),
                previous_turn_index=current_session.get("current_turn"),
                new_turn_index=(current_session.get("current_turn") or 1) + 1,
                fallback_reason=reason,
                failure_detail=failure_detail,
                provider_stage=provider_stage,
                fallback_shared_situation_preview=_short_debug_text(fallback_result["shared_situation"], 240),
                **selection_debug
            )
            _log_provider_event(
                "joint_turn_generation_failed_using_fallback",
                debug_trace_id=debug_trace_id,
                fallback_reason=reason,
                failure_detail=failure_detail,
                provider_stage=provider_stage,
                exception_message=(str(exception) if exception is not None else ""),
                raw_reply_preview=raw_reply_preview,
                http_status=http_status
            )
            return fallback_result

        _log_provider_event(
            "joint_turn_generation_started",
            debug_trace_id=debug_trace_id,
            model=self.config.resolved_llm_model(),
            api_base=self.config.resolved_llm_api_base(),
            timeout_seconds=timeout_seconds,
            recent_shared_chat_count=len(recent_shared_chat or [])
        )
        _log_provider_event(
            "story_progression_generation_started",
            debug_trace_id=debug_trace_id,
            session_id=current_session.get("id"),
            previous_turn_index=current_session.get("current_turn"),
            new_turn_index=(current_session.get("current_turn") or 1) + 1,
            role_a_action_preview=_short_debug_text(role_a_action, 160),
            role_b_action_preview=_short_debug_text(role_b_action, 160),
            shared_chat_message_count=len(recent_shared_chat or []),
            progression_history_count=len(recent_turn_history or [])
        )
        _log_provider_event(
            "story_progression_prompt_built",
            debug_trace_id=debug_trace_id,
            session_id=current_session.get("id"),
            previous_turn_index=current_session.get("current_turn"),
            new_turn_index=(current_session.get("current_turn") or 1) + 1,
            role_a_action_preview=_short_debug_text(role_a_action, 160),
            role_b_action_preview=_short_debug_text(role_b_action, 160),
            shared_chat_message_count=len(recent_shared_chat or []),
            progression_history_count=len(recent_turn_history or []),
            prompt_preview=_short_debug_text(prompt_text, 280),
            **selection_debug
        )
        _write_story_progression_prompt_debug_file(prompt_text)

        try:
            http_status, response_body, elapsed_seconds = self._perform_chat_completion_request(
                endpoint=endpoint,
                request_body=request_body,
                headers=headers,
                timeout_seconds=timeout_seconds
            )
            extraction = _extract_chat_completion_result(json.loads(response_body))
            if not extraction["reply_extracted"]:
                return use_fallback(
                    "empty_response",
                    failure_detail="empty_response",
                    provider_stage="empty_response",
                    raw_reply_preview="",
                    http_status=http_status
                )

            raw_reply_text = extraction["text"]
            try:
                raw_json_result = _extract_json_object_from_text(raw_reply_text)
            except json.JSONDecodeError as exc:
                return use_fallback(
                    "json_parse_failed",
                    failure_detail="json_parse_failed",
                    provider_stage="json_parse_failed",
                    exception=exc,
                    raw_reply_preview=_short_debug_text(raw_reply_text, 240),
                    http_status=http_status
                )
            except ValueError as exc:
                return use_fallback(
                    "json_parse_failed",
                    failure_detail="json_parse_failed",
                    provider_stage="json_parse_failed",
                    exception=exc,
                    raw_reply_preview=_short_debug_text(raw_reply_text, 240),
                    http_status=http_status
                )

            try:
                parsed_result = _normalize_joint_turn_generation_result(
                    raw_json_result,
                    fallback_result=fallback_result
                )
                _validate_joint_story_progression_result(parsed_result)
            except ValueError as exc:
                error_text = str(exc)
                if error_text == "Abstract shared_situation.":
                    _log_provider_event(
                        "story_progression_generation_failed",
                        debug_trace_id=debug_trace_id,
                        session_id=current_session.get("id"),
                        previous_turn_index=current_session.get("current_turn"),
                        new_turn_index=(current_session.get("current_turn") or 1) + 1,
                        fallback_reason="parser_failed",
                        failure_detail="abstract_shared_situation",
                        provider_stage="abstract_retry_requested",
                        raw_reply_preview=_short_debug_text(raw_reply_text, 240),
                        will_retry=True,
                        **selection_debug
                    )
                    retry_messages = _build_joint_progression_retry_messages(base_messages, raw_reply_text)
                    retry_payload = {
                        "model": self.config.resolved_llm_model(),
                        "messages": retry_messages,
                        "stream": False
                    }
                    retry_request_body = json.dumps(retry_payload).encode("utf-8")
                    retry_http_status, retry_response_body, retry_elapsed_seconds = self._perform_chat_completion_request(
                        endpoint=endpoint,
                        request_body=retry_request_body,
                        headers=headers,
                        timeout_seconds=timeout_seconds
                    )
                    retry_extraction = _extract_chat_completion_result(json.loads(retry_response_body))
                    if not retry_extraction["reply_extracted"]:
                        return use_fallback(
                            "empty_response",
                            failure_detail="empty_response",
                            provider_stage="retry_empty_response",
                            raw_reply_preview="",
                            http_status=retry_http_status
                        )
                    retry_raw_reply_text = retry_extraction["text"]
                    try:
                        retry_raw_json = _extract_json_object_from_text(retry_raw_reply_text)
                        parsed_result = _normalize_joint_turn_generation_result(
                            retry_raw_json,
                            fallback_result=fallback_result
                        )
                        _validate_joint_story_progression_result(parsed_result)
                        http_status = retry_http_status
                        elapsed_seconds = retry_elapsed_seconds
                        raw_reply_text = retry_raw_reply_text
                    except json.JSONDecodeError as retry_exc:
                        return use_fallback(
                            "json_parse_failed",
                            failure_detail="json_parse_failed",
                            provider_stage="retry_json_parse_failed",
                            exception=retry_exc,
                            raw_reply_preview=_short_debug_text(retry_raw_reply_text, 240),
                            http_status=retry_http_status
                        )
                    except ValueError as retry_exc:
                        retry_error_text = str(retry_exc)
                        if retry_error_text == "Missing shared_situation.":
                            return use_fallback(
                                "missing_shared_situation",
                                failure_detail="missing_shared_situation",
                                provider_stage="retry_missing_shared_situation",
                                exception=retry_exc,
                                raw_reply_preview=_short_debug_text(retry_raw_reply_text, 240),
                                http_status=retry_http_status
                            )
                        return use_fallback(
                            "parser_failed",
                            failure_detail=(
                                "abstract_text"
                                if retry_error_text == "Abstract shared_situation."
                                else "parser_failed"
                            ),
                            provider_stage="retry_parser_failed",
                            exception=retry_exc,
                            raw_reply_preview=_short_debug_text(retry_raw_reply_text, 240),
                            http_status=retry_http_status
                        )
                elif error_text == "Missing shared_situation.":
                    return use_fallback(
                        "missing_shared_situation",
                        failure_detail="missing_shared_situation",
                        provider_stage="missing_shared_situation",
                        exception=exc,
                        raw_reply_preview=_short_debug_text(raw_reply_text, 240),
                        http_status=http_status
                    )
                else:
                    return use_fallback(
                        "parser_failed",
                        failure_detail=(
                            "abstract_text"
                            if error_text == "Abstract shared_situation."
                            else "parser_failed"
                        ),
                        provider_stage="parser_failed",
                        exception=exc,
                        raw_reply_preview=_short_debug_text(raw_reply_text, 240),
                        http_status=http_status
                    )

            _log_provider_event(
                "joint_turn_llm_json_parsed",
                debug_trace_id=debug_trace_id,
                http_status=http_status
            )
            _log_provider_event(
                "joint_turn_next_situation_generated",
                debug_trace_id=debug_trace_id,
                next_situation_preview=_short_debug_text(parsed_result["next_situation"], 240)
            )
            _log_provider_event(
                "joint_turn_role_suggestions_generated",
                debug_trace_id=debug_trace_id,
                role_a_suggestion_preview=_short_debug_text(parsed_result["role_a_suggestion"], 160),
                role_b_suggestion_preview=_short_debug_text(parsed_result["role_b_suggestion"], 160)
            )
            _log_provider_event(
                "joint_turn_generation_completed",
                debug_trace_id=debug_trace_id,
                http_status=http_status,
                elapsed_seconds=round(elapsed_seconds, 3),
                next_situation_preview=_short_debug_text(parsed_result["next_situation"], 240)
            )
            _log_provider_event(
                "story_progression_generation_completed",
                debug_trace_id=debug_trace_id,
                session_id=current_session.get("id"),
                previous_turn_index=current_session.get("current_turn"),
                new_turn_index=(current_session.get("current_turn") or 1) + 1,
                role_a_action_preview=_short_debug_text(role_a_action, 160),
                role_b_action_preview=_short_debug_text(role_b_action, 160),
                shared_chat_message_count=len(recent_shared_chat or []),
                progression_history_count=len(recent_turn_history or []),
                shared_situation_preview=_short_debug_text(parsed_result["shared_situation"], 240),
                next_decision_point_preview=_short_debug_text(parsed_result["next_decision_point"], 180)
            )
            return parsed_result
        except (
            error.HTTPError,
            error.URLError,
            http.client.HTTPException,
            socket.timeout,
            TimeoutError,
            ValueError,
            KeyError,
            IndexError,
            json.JSONDecodeError
        ) as exc:
            return use_fallback(
                "llm_call_failed",
                failure_detail="llm_call_failed",
                provider_stage="llm_call_failed",
                exception=exc,
                raw_reply_preview=(
                    _short_debug_text(extraction["text"], 240)
                    if "extraction" in locals() and isinstance(extraction, dict)
                    else ""
                ),
                http_status=(http_status if "http_status" in locals() else None)
            )


_active_config = AIEngineConfig.from_env()
_local_provider: AIProvider = LocalDeterministicAIProvider()
_provider_registry: Dict[str, AIProvider] = {
    "local": _local_provider
}


def _refresh_placeholder_llm_provider():
    current_llm_provider: Optional[AIProvider] = _provider_registry.get("llm")
    if current_llm_provider is None or type(current_llm_provider) is DeepSeekOpenAICompatibleProvider:
        _provider_registry["llm"] = DeepSeekOpenAICompatibleProvider(_local_provider, _active_config)


_refresh_placeholder_llm_provider()


def configure_ai_engine(config):
    global _active_config
    _active_config = config
    _refresh_placeholder_llm_provider()


def get_ai_engine_config():
    return _active_config


def register_ai_provider(name, provider: AIProvider):
    normalized_name = (name or "").strip().lower()
    if normalized_name == "":
        raise ValueError("Provider name cannot be empty.")
    _provider_registry[normalized_name] = provider


def get_active_ai_provider() -> AIProvider:
    provider_name = _active_config.resolved_provider_name()
    if provider_name == "deepseek":
        provider_name = "llm"
    return _provider_registry.get(provider_name, _provider_registry["local"])


def build_turn_coach_prompt(
    current_session,
    user_role,
    user_profile=None,
    recent_turn_history=None
):
    return get_active_ai_provider().build_turn_coach_prompt(
        current_session=current_session,
        user_role=user_role,
        user_profile=user_profile,
        recent_turn_history=recent_turn_history
    )


def validate_turn_action(action_text, current_session, user_role):
    return get_active_ai_provider().validate_turn_action(
        action_text=action_text,
        current_session=current_session,
        user_role=user_role
    )


def evaluate_turn_action(
    action_text,
    current_session,
    user_role,
    recent_turn_history=None,
    debug_trace_id=None
):
    return get_active_ai_provider().evaluate_turn_action(
        action_text=action_text,
        current_session=current_session,
        user_role=user_role,
        recent_turn_history=recent_turn_history,
        debug_trace_id=debug_trace_id
    )


def generate_dynamic_ai_feedback(
    user_role,
    user_text,
    current_turn,
    current_situation,
    current_session=None,
    user_profile=None,
    recent_turn_history=None,
    recent_coach_history=None,
    debug_trace_id=None
):
    return get_active_ai_provider().generate_dynamic_ai_feedback(
        user_role=user_role,
        user_text=user_text,
        current_turn=current_turn,
        current_situation=current_situation,
        current_session=current_session,
        user_profile=user_profile,
        recent_turn_history=recent_turn_history,
        recent_coach_history=recent_coach_history,
        debug_trace_id=debug_trace_id
    )


def generate_next_situation(
    current_session,
    user_role,
    action_text,
    recent_turn_history=None,
    debug_trace_id=None
):
    return get_active_ai_provider().generate_next_situation(
        current_session=current_session,
        user_role=user_role,
        action_text=action_text,
        recent_turn_history=recent_turn_history,
        debug_trace_id=debug_trace_id
    )


def generate_next_situation_from_joint_actions(
    current_session,
    role_a_action,
    role_b_action,
    recent_turn_history=None,
    recent_shared_chat=None,
    debug_trace_id=None
):
    return get_active_ai_provider().generate_next_situation_from_joint_actions(
        current_session=current_session,
        role_a_action=role_a_action,
        role_b_action=role_b_action,
        recent_turn_history=recent_turn_history,
        recent_shared_chat=recent_shared_chat,
        debug_trace_id=debug_trace_id
    )
