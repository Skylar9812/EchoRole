"""Replaceable AI engine boundary for EchoRole.

Today's default behavior stays local and deterministic. A small provider and
config layer sits underneath the public helper functions so a future real LLM
provider can be plugged in without changing app.py.
"""

import json
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
    provider_name: str = "local"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_api_base: str = ""
    llm_timeout_seconds: float = 12.0

    @classmethod
    def from_env(cls):
        return cls(
            provider_name=os.getenv("ECHOROLE_AI_PROVIDER", "local"),
            llm_api_key=os.getenv("ECHOROLE_LLM_API_KEY", ""),
            llm_model=os.getenv("ECHOROLE_LLM_MODEL", ""),
            llm_api_base=os.getenv("ECHOROLE_LLM_API_BASE", "")
        )

    def resolved_provider_name(self):
        return (self.provider_name or "local").strip().lower()

    def resolved_llm_api_key(self):
        return (self.llm_api_key or "").strip()

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
        debug_trace_id=None
    ):
        raise NotImplementedError


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

    history_section = ""
    if recent_history_context:
        history_section = f"Recent progression history:\n{recent_history_context}\n\n"

    return (
        f"Turn {current_session['current_turn']}\n\n"
        f"Current situation: {current_session['current_situation']}\n\n"
        f"Your private role brief: {role_brief}\n\n"
        f"{profile_section}"
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

TURN_ACTION_COUNTERPART_TERMS = [
    "boss", "child", "client", "colleague", "coworker", "co-worker",
    "daughter", "employee", "father", "friend", "he", "her", "him",
    "manager", "member", "mother", "our", "parent", "partner", "roommate",
    "son", "student", "supervisor", "teammate", "teammate", "teacher",
    "them", "their", "wife", "husband", "girlfriend", "boyfriend",
]

TURN_ACTION_EMOTION_KEYWORDS = [
    "angry", "anxious", "annoyed", "ashamed", "disappointed", "frustrated",
    "hurt", "mad", "nervous", "overwhelmed", "sad", "stressed", "upset",
    "worried",
]

TURN_ACTION_VAGUE_PHRASES = [
    "do better", "do something", "fix it", "handle it", "be nice",
    "be better", "calm down", "try harder", "make it work", "say something",
    "deal with it", "figure it out",
]

TURN_ACTION_META_PHRASES = [
    "advance the story", "advance turn", "ask the ai", "generate next turn",
    "generate the next scene", "reload turn",
]

TURN_ACTION_CLEARLY_UNRELATED_PHRASES = [
    "buy a spaceship", "cast a spell", "fight a dragon", "hack the database",
    "leave the planet", "summon a dragon", "teleport away",
]

TURN_ACTION_UNSAFE_PHRASES = [
    "abuse", "blackmail", "hit", "hurt them", "hurt her", "hurt him",
    "intimidate", "kill", "punch", "shove", "slap", "threat", "threaten",
]


def _contains_prefixed_word(words, prefixes):
    return any(
        word.startswith(prefix)
        for word in words
        for prefix in prefixes
    )


def _has_social_action_signal(lowered, words):
    return _contains_prefixed_word(words, TURN_ACTION_SOCIAL_PREFIXES) or any(
        phrase in lowered for phrase in TURN_ACTION_SOCIAL_PHRASES
    )


def _has_counterpart_or_context_signal(lowered, words):
    if any(term in lowered for term in TURN_ACTION_COUNTERPART_TERMS):
        return True

    if '"' in lowered:
        return True

    content_words = [word for word in words if len(word) >= 3]
    return len(content_words) >= 5


def _is_meta_turn_action(lowered):
    return any(phrase in lowered for phrase in TURN_ACTION_META_PHRASES)


def _is_clearly_unrelated_turn_action(lowered):
    return any(phrase in lowered for phrase in TURN_ACTION_CLEARLY_UNRELATED_PHRASES)


def _is_unsafe_turn_action(lowered):
    return any(phrase in lowered for phrase in TURN_ACTION_UNSAFE_PHRASES)


def _validate_turn_action_local(action_text, current_session, user_role):
    text = action_text.strip()
    lowered = text.lower()
    words = re.findall(r"[a-zA-Z']+", lowered)

    has_social_action = _has_social_action_signal(lowered, words)
    has_emotion_keyword = any(keyword in lowered for keyword in TURN_ACTION_EMOTION_KEYWORDS)
    is_short = len(words) < 2 or len(text) < 8
    is_vague_phrase = any(phrase in lowered for phrase in TURN_ACTION_VAGUE_PHRASES)
    has_counterpart_or_context = _has_counterpart_or_context_signal(lowered, words)

    if is_short:
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "Please describe one concrete action you take next, such as what you say, ask, offer, accept, refuse, or suggest."
            )
        }

    if _is_meta_turn_action(lowered):
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "Please describe one concrete action your character takes next, not a command to the app or AI."
            )
        }

    if _is_clearly_unrelated_turn_action(lowered):
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "Please keep it to a believable interpersonal move in the current role-play."
            )
        }

    if _is_unsafe_turn_action(lowered):
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "Please describe a concrete next move that is not violent, coercive, or abusive."
            )
        }

    if not has_social_action:
        if has_emotion_keyword:
            reason = "It mainly expresses a feeling, but it does not yet describe a concrete move."
        else:
            reason = "It does not yet describe one clear interpersonal action."

        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                f"{reason} Please describe one concrete action you take next, such as what you say, ask, offer, accept, refuse, or suggest."
            )
        }

    if is_vague_phrase or (has_social_action and len(words) < 5 and not has_counterpart_or_context):
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "The intention is understandable, but the move is still too vague. "
                "Please describe one concrete action you take next, such as what you say, ask, offer, accept, refuse, or suggest."
            )
        }

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
    text = (action_text or "").strip()
    lowered = text.lower()
    words = re.findall(r"[a-zA-Z']+", lowered)

    risk_flags = []

    if _is_unsafe_turn_action(lowered) or any(
        keyword in lowered
        for keyword in ["violent", "violence", "scream at", "yell at", "abusive"]
    ):
        risk_flags.append("unsafe")

    if any(keyword in lowered for keyword in ["yell", "scream", "blame", "attack", "punish"]):
        risk_flags.append("escalatory")

    if len(words) < 2 or len(text) < 8:
        risk_flags.append("too brief")

    if any(phrase in lowered for phrase in TURN_ACTION_VAGUE_PHRASES):
        risk_flags.append("too vague")

    has_social_action = _has_social_action_signal(lowered, words)
    has_counterpart_or_context = _has_counterpart_or_context_signal(lowered, words)

    if not has_social_action:
        risk_flags.append("not actionable")
    elif len(words) < 5 and not has_counterpart_or_context:
        risk_flags.append("too vague")

    if _is_meta_turn_action(lowered) or _is_clearly_unrelated_turn_action(lowered):
        risk_flags.append("unrelated")

    return risk_flags


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
    _log_provider_event(
        "ai_coach_rag_context_built",
        debug_trace_id=debug_trace_id,
        first_coach_reply=first_coach_reply,
        retrieved_note_count=len(rag_notes),
        retrieved_note_titles=[note.get("title") for note in rag_notes],
        retrieved_note_sources=[note.get("relative_path") for note in rag_notes]
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

    if first_coach_reply:
        user_message += f"\nRetrieved local guidance notes:\n{rag_notes_context}\n"

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]
    prompt_text = f"{system_message}\n\n{user_message}".strip()
    return {
        "messages": messages,
        "rag_note_count": len(rag_notes),
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
    recent_turn_history=None
):
    recent_history_context = format_recent_turn_history(recent_turn_history)
    if recent_history_context == "":
        recent_history_context = "No prior turn history available."

    system_message = (
        "You are generating the next turn platform for an interpersonal role-play training simulation. "
        "Return strict JSON only with exactly these keys: next_situation, role_a_suggestion, role_b_suggestion. "
        "Do not judge validity, do not declare a winner, do not reveal private role briefs, and do not mention the prompt or system instructions."
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
        "Requirements for next_situation:\n"
        "- neutral third-person narration\n"
        "- maximum 3 sentences\n"
        "- sets up only the next conversational moment\n"
        "- reflects both actions fairly without over-explaining feelings\n"
        "- does not decide the next move for either participant\n"
        "- usually ends with an open question, tension point, or unresolved moment\n\n"
        "Requirements for role_a_suggestion and role_b_suggestion:\n"
        "- private coaching for that role only\n"
        "- 2 to 4 concise bullet points or short sentences\n"
        "- written in second person\n"
        "- may refer to visible actions and the shared situation\n"
        "- must not reveal the other role's private brief\n\n"
        "Return JSON only in this exact shape:\n"
        "{\n"
        '  "next_situation": "...",\n'
        '  "role_a_suggestion": "...",\n'
        '  "role_b_suggestion": "..."\n'
        "}"
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


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
    role_a_suggestion,
    role_b_suggestion
):
    return {
        "next_situation": str(next_situation or "").strip(),
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


def _build_default_joint_turn_result(
    current_session,
    role_a_action,
    role_b_action
):
    next_situation = _generate_next_situation_from_joint_actions_local(
        current_session=current_session,
        role_a_action=role_a_action,
        role_b_action=role_b_action
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
        next_situation=next_situation,
        role_a_suggestion=role_a_suggestion,
        role_b_suggestion=role_b_suggestion
    )


def _normalize_joint_turn_generation_result(raw_result, fallback_result):
    if not isinstance(raw_result, dict):
        raise ValueError("Joint turn result must be a JSON object.")

    next_situation = _limit_to_max_sentences(
        str(raw_result.get("next_situation") or "").strip(),
        max_sentences=3
    )
    if next_situation == "":
        raise ValueError("Missing next_situation.")

    role_a_suggestion = _normalize_suggestion_text(raw_result.get("role_a_suggestion"))
    role_b_suggestion = _normalize_suggestion_text(raw_result.get("role_b_suggestion"))

    if role_a_suggestion == "":
        role_a_suggestion = fallback_result["role_a_suggestion"]
    if role_b_suggestion == "":
        role_b_suggestion = fallback_result["role_b_suggestion"]

    return _build_joint_turn_generation_result(
        next_situation=next_situation,
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
    role_a_signal = classify_action_signal(role_a_action)
    role_b_signal = classify_action_signal(role_b_action)

    if "escalate" in {role_a_signal, role_b_signal}:
        return (
            "Both sides have now put their positions on the table, and the tension in the conversation is harder to ignore. "
            "Who will try to slow the exchange down without backing away from the issue?"
        )
    elif "repair" in {role_a_signal, role_b_signal} and "clarify" in {role_a_signal, role_b_signal}:
        return (
            "Both sides have started addressing the issue more directly, but the disagreement is still unresolved. "
            "What will each person choose to clarify first?"
        )

    return (
        "Both sides have now responded to the issue, and the conversation is moving into a more direct phase. "
        "What will each person decide to put on the table next?"
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
            llm_call_attempted=False,
            llm_call_succeeded=False,
            llm_http_status=None,
            reply_extracted=(feedback or "").strip() != "",
            reply_length=len((feedback or "").strip()),
            reply_preview=_short_debug_text(feedback),
            content_type="local_string",
            used_fallback=False,
            fallback_reason="",
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
        debug_trace_id=None
    ):
        return _build_default_joint_turn_result(
            current_session=current_session,
            role_a_action=role_a_action,
            role_b_action=role_b_action
        )


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
            return response.status, response_body, elapsed_seconds
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
        fallback_feedback = self.fallback_provider.generate_dynamic_ai_feedback(
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
        timeout_seconds = self.config.resolved_llm_timeout_seconds()
        debug_info = {
            "provider": "llm",
            "provider_stage": "entering_provider",
            "llm_call_attempted": True,
            "llm_call_succeeded": False,
            "llm_http_status": None,
            "reply_extracted": False,
            "reply_length": 0,
            "reply_preview": "",
            "content_type": "missing",
            "used_fallback": True,
            "fallback_reason": "",
            "response_choice_count": 0,
            "has_reasoning_content": False,
            "reasoning_length": 0,
            "fallback_reply_length": len((fallback_feedback or "").strip()),
            "fallback_reply_preview": _short_debug_text(fallback_feedback),
            "llm_model": self.config.resolved_llm_model(),
            "llm_api_base": self.config.resolved_llm_api_base(),
            "llm_timeout_seconds": timeout_seconds,
            "pipeline_error": "",
        }

        def sync_debug(stage=None, **updates):
            if stage is not None:
                debug_info["provider_stage"] = stage
            debug_info.update(updates)
            _set_last_ai_debug_info(**debug_info)

        def start_fallback(reason, pipeline_error, event_fields=None):
            debug_info["fallback_reason"] = reason
            debug_info["pipeline_error"] = pipeline_error
            sync_debug("fallback_started")
            _log_provider_event(
                "fallback_started",
                debug_trace_id=debug_trace_id,
                fallback_reason=reason,
                pipeline_error=pipeline_error,
                **(event_fields or {})
            )
            sync_debug("fallback_completed")
            _log_provider_event(
                "fallback_completed",
                debug_trace_id=debug_trace_id,
                fallback_reason=reason,
                fallback_reply_length=len((fallback_feedback or "").strip())
            )
            return fallback_feedback

        sync_debug("entering_provider")
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
                }
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
                    event_fields={"http_status": exc.code}
                )
            elif isinstance(exc, error.URLError):
                reason_text = str(exc.reason).lower()
                if "timed out" in reason_text or "timeout" in reason_text:
                    return start_fallback(
                        reason="http_timeout",
                        pipeline_error=(
                            f"DeepSeek request timed out after {timeout_seconds:.1f} seconds."
                        ),
                        event_fields={"network_reason": str(exc.reason)}
                    )
                else:
                    return start_fallback(
                        reason="network_error",
                        pipeline_error=f"DeepSeek network error: {exc.reason}",
                        event_fields={"network_reason": str(exc.reason)}
                    )
            elif isinstance(exc, socket.timeout):
                return start_fallback(
                    reason="http_timeout",
                    pipeline_error=(
                        f"DeepSeek request timed out after {timeout_seconds:.1f} seconds."
                    )
                )
            elif isinstance(exc, json.JSONDecodeError):
                return start_fallback(
                    reason="invalid_json",
                    pipeline_error="DeepSeek returned invalid JSON."
                )
            elif isinstance(exc, http.client.HTTPException):
                return start_fallback(
                    reason="http_exception",
                    pipeline_error=f"DeepSeek HTTP client error: {exc}"
                )
            elif isinstance(exc, TimeoutError):
                return start_fallback(
                    reason="http_timeout",
                    pipeline_error=(
                        f"DeepSeek request timed out after {timeout_seconds:.1f} seconds."
                    )
                )
            else:
                return start_fallback(
                    reason="llm_exception",
                    pipeline_error=str(exc)
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
        debug_trace_id=None
    ):
        fallback_result = self.fallback_provider.generate_next_situation_from_joint_actions(
            current_session=current_session,
            role_a_action=role_a_action,
            role_b_action=role_b_action,
            recent_turn_history=recent_turn_history,
            debug_trace_id=debug_trace_id
        )
        api_key = self.config.resolved_llm_api_key()
        if api_key == "":
            _log_provider_event(
                "joint_turn_generation_failed_using_fallback",
                debug_trace_id=debug_trace_id,
                fallback_reason="missing_api_key"
            )
            return fallback_result

        endpoint = f"{self.config.resolved_llm_api_base()}/chat/completions"
        timeout_seconds = self.config.resolved_llm_timeout_seconds()
        payload = {
            "model": self.config.resolved_llm_model(),
            "messages": _build_llm_joint_next_situation_messages(
                current_session=current_session,
                role_a_action=role_a_action,
                role_b_action=role_b_action,
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
            "joint_turn_generation_started",
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
                    "joint_turn_generation_failed_using_fallback",
                    debug_trace_id=debug_trace_id,
                    fallback_reason="empty_llm_reply",
                    http_status=http_status
                )
                return fallback_result

            parsed_result = _normalize_joint_turn_generation_result(
                _extract_json_object_from_text(extraction["text"]),
                fallback_result=fallback_result
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
            _log_provider_event(
                "joint_turn_generation_failed_using_fallback",
                debug_trace_id=debug_trace_id,
                fallback_reason=type(exc).__name__,
                exception_message=str(exc),
                raw_reply_preview=(
                    _short_debug_text(extraction["text"], 240)
                    if "extraction" in locals() and isinstance(extraction, dict)
                    else ""
                )
            )
            return fallback_result


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
    debug_trace_id=None
):
    return get_active_ai_provider().generate_next_situation_from_joint_actions(
        current_session=current_session,
        role_a_action=role_a_action,
        role_b_action=role_b_action,
        recent_turn_history=recent_turn_history,
        debug_trace_id=debug_trace_id
    )
