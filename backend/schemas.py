"""Explicit public response models. Never serialize entire legacy records."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    display_name: str = Field(min_length=1)
    mbti: str = ""
    priorities: str = ""


class ProfileState(BaseModel):
    user_id: str
    display_name: str
    mbti: str
    priorities: str


class ProfileResponse(ProfileState):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class RoomResponse(BaseModel):
    id: int
    invite_code: str
    created_at: str
    event_version: int


class MemberResponse(BaseModel):
    user_id: str
    nickname: str | None
    joined_at: str


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    expected_session_id: int | None = Field(default=None, gt=0)


class SessionResponse(BaseModel):
    id: int
    room_id: int
    title: str
    context: str
    conflict: str
    opening_situation: str
    current_turn: int
    current_situation: str
    created_at: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["echorole-api"] = "echorole-api"


class ScenarioPreview(BaseModel):
    id: str
    title: str
    category: str
    context: str
    conflict: str
    opening_situation: str
