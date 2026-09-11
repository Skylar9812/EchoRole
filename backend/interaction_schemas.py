"""Typed interactive contracts. Shared projections contain no role-private payloads."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RequestBody(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ChatSend(RequestBody):
    content: str = Field(min_length=1, max_length=20000)
    request_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


class CoachSend(ChatSend):
    turn_index: int = Field(ge=1)


class TurnRequest(RequestBody):
    turn_index: int = Field(ge=1)


class ActionSend(TurnRequest):
    action_text: str = Field(min_length=1, max_length=20000)


class Recovery(RequestBody):
    attempt_id: str = Field(min_length=1, max_length=64)
    acknowledge_uncertain: Literal[True]


class TurnRecovery(Recovery):
    turn_index: int = Field(ge=1)


class SharedMessage(BaseModel):
    id: int
    user_id: str
    username: str | None
    content: str
    created_at: str


class BriefEntry(BaseModel):
    turn_number: int
    brief_text: str
    created_at: str


class PrivateState(BaseModel):
    session_id: int
    turn_index: int
    role_name: Literal['role_a','role_b']
    brief: str
    brief_history: list[BriefEntry]
    pressure: str
    next_decision_point: str


class CoachMessage(BaseModel):
    turn_index: int
    sender: Literal['user','ai']
    content: str
    created_at: str


class CoachResult(BaseModel):
    request_id: str
    turn_index: int
    state: Literal['running','ready','completed','uncertain']
    attempt_id: str
    reply: str | None


class Suggestion(BaseModel):
    turn_index: int
    text: str


class TurnStatus(BaseModel):
    session_id: int
    turn_index: int
    current_turn: int
    state: Literal['action_required','submitted','waiting_for_other','generating','advanced','uncertain']
    submitted: bool
    other_submitted: bool
    own_action: str | None
    attempt_id: str | None
    current_situation: str


class ProgressionEntry(BaseModel):
    turn_index: int
    resulting_situation: str
    created_at: str
