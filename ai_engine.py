"""Local deterministic AI engine for EchoRole.

This module is the replaceable boundary for future LLM integration. The
functions here intentionally keep today's behavior local and deterministic.
"""

import re


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


def build_turn_coach_prompt(current_session, user_role):
    role_brief = get_role_brief(current_session, user_role)
    if role_brief.strip() == "":
        return ""

    return (
        f"Turn {current_session['current_turn']}\n\n"
        f"Current situation: {current_session['current_situation']}\n\n"
        f"Your private role brief: {role_brief}\n\n"
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


def validate_turn_action(action_text, current_session, user_role):
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


def generate_dynamic_ai_feedback(user_role, user_text, current_turn, current_situation):
    signal = classify_action_signal(user_text)
    role_label = get_role_label(user_role)

    if signal == "repair":
        coaching_focus = "That move can reduce defensiveness, but it will only feel credible if your wording is specific and accountable."
    elif signal == "clarify":
        coaching_focus = "Clarifying can be productive here, especially if you separate facts, emotions, and requests instead of blending them together."
    elif signal == "escalate":
        coaching_focus = "That move may create short-term control, but it also risks hardening the other person's stance and narrowing the room for repair."
    else:
        coaching_focus = "There is room to explore, but you may need to state your intention more clearly so the next move changes the interaction instead of prolonging uncertainty."

    return (
        f"From {role_label}'s perspective in turn {current_turn}, notice what this situation is pulling you toward: "
        f"{current_situation} {coaching_focus} "
        "Before you act, try naming the outcome you want, the emotion you need to regulate, and the one sentence you most want the other person to understand."
    )


def generate_next_situation(current_session, user_role, action_text):
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
