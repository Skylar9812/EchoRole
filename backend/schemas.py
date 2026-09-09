"""Explicit public response models. Never serialize entire legacy records."""
from typing import Literal
from pydantic import BaseModel


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
