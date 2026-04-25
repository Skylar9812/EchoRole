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
import socket
import time
from typing import Any, Dict, Optional
from urllib import error
from urllib.parse import urlsplit

_last_ai_debug_info: Dict[str, Any] = {}


def get_role_brief(current_session, user_role):
    if user_role == "role_a":
        return current_session.get("role_a_brief", "")
    if user_role == "role_b":
        return current_session.get("role_b_brief", "")
    return ""


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
    display_name = user_profile.get("display_name", "").strip()
    mbti = user_profile.get("mbti", "").strip()
    priorities = user_profile.get("priorities", "").strip()

    if display_name:
        parts.append(f"display name: {display_name}")
    if mbti:
        parts.append(f"MBTI: {mbti}")
    if priorities:
        parts.append(f"communication/value priorities: {priorities}")

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


def _short_debug_text(text, limit=180):
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


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

    def generate_dynamic_ai_feedback(
        self,
        user_role,
        user_text,
        current_turn,
        current_situation,
        user_profile=None,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        raise NotImplementedError

    def generate_next_situation(self, current_session, user_role, action_text):
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


def _validate_turn_action_local(action_text, current_session, user_role):
    text = action_text.strip()
    lowered = text.lower()
    words = re.findall(r"[a-zA-Z']+", lowered)

    action_keywords = [
        "ask", "tell", "message", "apologize", "apologise", "propose",
        "listen", "explain", "clarify", "request", "schedule", "meet",
        "offer", "set", "agree", "discuss", "acknowledge", "invite",
        "negotiate", "share", "restate", "summarize", "summarise"
    ]
    emotion_keywords = [
        "angry", "mad", "upset", "hurt", "sad", "frustrated",
        "annoyed", "stressed", "unfair", "disappointed"
    ]
    vague_phrases = [
        "do better", "fix it", "handle it", "be nice", "be better",
        "calm down", "try harder", "make it work", "talk to them",
        "say something", "deal with it"
    ]
    interpersonal_terms = [
        "manager", "member", "team", "supervisor", "colleague", "client",
        "they", "them", "their", "other", "person", "conversation",
        "meeting", "message", "email", "call", "deadline", "workload",
        "support", "expectation", "feedback", "apology", "apologize",
        "apologise", "sorry", "listen", "clarify", "explain", "request",
        "discuss", "acknowledge", "negotiate", "offer"
    ]
    stopwords = {
        "about", "after", "again", "because", "before", "from", "have",
        "into", "that", "their", "them", "then", "there", "this", "will",
        "with", "what", "when", "where", "would", "could", "should"
    }

    role_label = get_role_label(user_role)
    has_action_keyword = any(keyword in lowered for keyword in action_keywords)
    has_emotion_keyword = any(keyword in lowered for keyword in emotion_keywords)
    is_short = len(words) < 5 or len(text) < 18
    is_vague_phrase = any(phrase in lowered for phrase in vague_phrases) and len(words) <= 8
    has_interpersonal_term = any(term in lowered for term in interpersonal_terms)

    context_text = " ".join([
        current_session.get("context", ""),
        current_session.get("conflict", ""),
        current_session.get("current_situation", ""),
        get_role_brief(current_session, user_role)
    ]).lower()
    context_terms = {
        word for word in re.findall(r"[a-zA-Z']+", context_text)
        if len(word) >= 4 and word not in stopwords
    }
    action_terms = {
        word for word in words
        if len(word) >= 4 and word not in stopwords
    }
    has_context_overlap = bool(context_terms.intersection(action_terms))

    if is_short:
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "It is too brief to create a believable next situation. "
                f"Revise it as a concrete move from {role_label}'s perspective: who you will address, what you will say or do, and what outcome you are trying to create."
            )
        }

    if not has_action_keyword:
        if has_emotion_keyword:
            reason = "It mainly expresses emotion, but it does not yet describe a concrete move."
        else:
            reason = "It does not clearly describe an interpersonal action the story can respond to."

        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                f"{reason} Try revising it into one actionable step, such as asking a clarifying question, making a specific request, offering an apology, or proposing a next conversation."
            )
        }

    if is_vague_phrase:
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "The intention is understandable, but the move is still too vague. "
                "Make it specific enough that the other person could realistically respond to it."
            )
        }

    if not has_interpersonal_term and not has_context_overlap:
        return {
            "is_valid": False,
            "feedback": (
                f"I cannot advance the story from this action yet: \"{text}\". "
                "It reads as unrelated to the current interpersonal situation. "
                "Revise it so the action clearly connects to the conflict, the other person, or the working relationship."
            )
        }

    return {
        "is_valid": True,
        "feedback": ""
    }


def _generate_dynamic_ai_feedback_local(
    user_role,
    user_text,
    current_turn,
    current_situation,
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

    return (
        f"From {role_label}'s perspective in turn {current_turn}, notice what this situation is pulling you toward: "
        f"{current_situation} Your recent reflection was: \"{user_text.strip()}\". {coaching_focus}"
        f"{personalization}{continuity} "
        "Before you act, try naming the outcome you want, the emotion you need to regulate, and the one sentence you most want the other person to understand."
    )


def _build_llm_coach_feedback_messages(
    user_role,
    user_text,
    current_turn,
    current_situation,
    user_profile=None,
    recent_turn_history=None
):
    role_label = get_role_label(user_role)
    profile_context = format_user_profile_context(user_profile) or "None provided."
    recent_history_context = format_recent_turn_history(recent_turn_history)
    if recent_history_context == "":
        recent_history_context = "No recent turn history available."

    local_style_anchor = _generate_dynamic_ai_feedback_local(
        user_role=user_role,
        user_text=user_text,
        current_turn=current_turn,
        current_situation=current_situation,
        user_profile=user_profile,
        recent_turn_history=recent_turn_history
    )

    system_message = (
        "You are EchoRole's private AI Coach for interpersonal decision training. "
        "Respond only with coaching feedback for the current user's private reflection. "
        "Do not advance the story, do not produce shared-chat dialogue, and do not role-play the other user. "
        "Keep the response supportive, reflective, practical, and concise."
    )
    user_message = (
        f"Role perspective: {role_label}\n"
        f"Current turn: {current_turn}\n"
        f"Current situation: {current_situation}\n"
        f"User profile: {profile_context}\n"
        f"Recent turn history:\n{recent_history_context}\n\n"
        f"Recent reflection:\n{user_text.strip()}\n\n"
        f"Style anchor from the deterministic local coach:\n{local_style_anchor}\n\n"
        "Write one short coaching response in plain text."
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]


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

    def generate_dynamic_ai_feedback(
        self,
        user_role,
        user_text,
        current_turn,
        current_situation,
        user_profile=None,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        feedback = _generate_dynamic_ai_feedback_local(
            user_role=user_role,
            user_text=user_text,
            current_turn=current_turn,
            current_situation=current_situation,
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

    def generate_next_situation(self, current_session, user_role, action_text):
        return _generate_next_situation_local(
            current_session=current_session,
            user_role=user_role,
            action_text=action_text
        )


class DeepSeekOpenAICompatibleProvider(AIProvider):
    """DeepSeek-backed OpenAI-compatible provider for coach feedback only."""

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

    def generate_dynamic_ai_feedback(
        self,
        user_role,
        user_text,
        current_turn,
        current_situation,
        user_profile=None,
        recent_turn_history=None,
        debug_trace_id=None
    ):
        fallback_feedback = self.fallback_provider.generate_dynamic_ai_feedback(
            user_role=user_role,
            user_text=user_text,
            current_turn=current_turn,
            current_situation=current_situation,
            user_profile=user_profile,
            recent_turn_history=recent_turn_history,
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

        payload = {
            "model": self.config.resolved_llm_model(),
            "messages": _build_llm_coach_feedback_messages(
                user_role=user_role,
                user_text=user_text,
                current_turn=current_turn,
                current_situation=current_situation,
                user_profile=user_profile,
                recent_turn_history=recent_turn_history
            ),
            "stream": False
        }

        endpoint = f"{self.config.resolved_llm_api_base()}/chat/completions"
        request_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        sync_debug("before_http_request")
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

    def generate_next_situation(self, current_session, user_role, action_text):
        return self.fallback_provider.generate_next_situation(
            current_session=current_session,
            user_role=user_role,
            action_text=action_text
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


def generate_dynamic_ai_feedback(
    user_role,
    user_text,
    current_turn,
    current_situation,
    user_profile=None,
    recent_turn_history=None,
    debug_trace_id=None
):
    return get_active_ai_provider().generate_dynamic_ai_feedback(
        user_role=user_role,
        user_text=user_text,
        current_turn=current_turn,
        current_situation=current_situation,
        user_profile=user_profile,
        recent_turn_history=recent_turn_history,
        debug_trace_id=debug_trace_id
    )


def generate_next_situation(current_session, user_role, action_text):
    return get_active_ai_provider().generate_next_situation(
        current_session=current_session,
        user_role=user_role,
        action_text=action_text
    )
