"""Shared synchronous application operations; no UI, HTTP, or AI dependencies.

Entrypoints explicitly initialize using the idempotent legacy initializer. Existing persistence and transaction
semantics remain in database.py. Callers own presentation and credentials.
"""
import random
import string
import uuid
import database as db
from scenario_library import get_scenario_by_id


class ApplicationError(ValueError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def initialize():
    db.init_db()


get_user_profile = db.get_user_profile
save_user_profile = db.save_user_profile
get_members_by_room = db.get_members_by_room
get_room_by_code = db.get_room_by_code
get_session_by_room = db.get_session_by_room
can_user_join_room = db.can_user_join_room


def create_profile(display_name, mbti=None, priorities=None, user_id=None):
    user_id = user_id or str(uuid.uuid4())
    db.save_user_profile(user_id, display_name, mbti, priorities)
    return db.get_user_profile(user_id)


def room_state(room_id):
    room = db.get_room_by_id(room_id)
    if room is None:
        raise ApplicationError("Room not found", 404)
    return dict(id=room[0], invite_code=room[1], created_at=room[2],
                event_version=db.get_room_event_version(room_id))


def create_room(user_id, nickname, *, sync=None):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    room_id = db.create_room(code)
    db.add_member(user_id, room_id, nickname)
    (sync or db.bump_room_event_version)(room_id=room_id, event_type="room_created")
    return room_state(room_id)


def join_room(room_id, user_id, nickname=None, *, sync=None, restore=False, activate=False):
    room_state(room_id)
    allowed, reason = db.can_user_join_room(room_id, user_id)
    if not allowed:
        raise ApplicationError(reason)
    db.add_member(user_id, room_id, nickname)
    if not restore:
        (sync or db.bump_room_event_version)(room_id=room_id, event_type="member_joined")
    if activate:
        session = db.get_session_by_room(room_id)
        if session:
            ensure_role(session["id"], user_id)
    return room_state(room_id)


def list_members(room_id):
    room_state(room_id)
    return [dict(user_id=u, nickname=n, joined_at=j) for u, n, j in db.get_members_by_room(room_id)]


def require_member(room_id, user_id):
    room_state(room_id)
    if user_id not in [row[0] for row in db.get_members_by_room(room_id)]:
        raise ApplicationError("Room membership required", 403)


def create_scenario_session(room_id, scenario, *, sync=None):
    room_state(room_id)
    if isinstance(scenario, str):
        scenario = get_scenario_by_id(scenario)
    if scenario is None:
        raise ApplicationError("Scenario not found", 404)
    session_id = db.create_session_from_scenario(room_id, scenario)
    members = db.get_members_by_room(room_id)
    for member, role in zip(members, ("role_a", "role_b")):
        db.assign_role(session_id, member[0], role)
    (sync or db.bump_room_event_version)(room_id=room_id, session_id=session_id,
                                        event_type="scenario_session_created")
    return session_id


def ensure_role(session_id, user_id):
    role = db.get_user_role(session_id, user_id)
    if role:
        return role
    assigned = [row[1] for row in db.get_all_roles_in_session(session_id)]
    for role in ("role_a", "role_b"):
        if role not in assigned:
            db.assign_role(session_id, user_id, role)
            return role
    raise ApplicationError("This active session already has two assigned participants.")


def public_session(room_id):
    room_state(room_id)
    session = db.get_session_by_room(room_id)
    if session is None:
        return None
    fields = ("id", "room_id", "title", "context", "conflict", "opening_situation",
              "current_turn", "current_situation", "created_at")
    return {field: session[field] for field in fields}
