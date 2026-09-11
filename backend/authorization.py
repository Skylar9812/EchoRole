"""Reusable gates for participant-private brief, coach and suggestion routes.

Data queries must also be scoped by the returned participant user/role.
"""
from dataclasses import dataclass
from typing import Literal
from fastapi import Depends
import application as services
from backend.identity import current_user


@dataclass(frozen=True)
class SessionParticipant:
    user_id: str
    session_id: int
    role_name: str


# current_user is the authenticated-participant dependency.
def room_member(room_id: int, user_id: str = Depends(current_user)) -> str:
    services.require_member(room_id, user_id)
    return user_id


def session_member(session_id: int, user_id: str = Depends(current_user)) -> SessionParticipant:
    role = services.require_session_member(session_id, user_id)
    return SessionParticipant(user_id, session_id, role)


def role_owner(role_name: Literal["role_a", "role_b"], participant: SessionParticipant = Depends(session_member)) -> SessionParticipant:
    services.require_role_owner(participant.session_id, participant.user_id, role_name)
    return participant
