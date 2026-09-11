"""Shared synchronous application operations; no UI, HTTP, or AI dependencies.

Entrypoints explicitly initialize using the idempotent legacy initializer.
Persistence remains in database.py; Phase 2 workflows share its atomic unit of
work. Callers own presentation and credentials.
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


@db.atomic
def create_room(user_id, nickname, *, sync=None):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    room_id = db.create_room(code)
    db.add_member(user_id, room_id, nickname)
    (sync or db.bump_room_event_version)(room_id=room_id, event_type="room_created")
    return room_state(room_id)


@db.atomic
def join_room(room_id, user_id, nickname=None, *, sync=None, restore=False, activate=False):
    room_state(room_id)
    allowed, reason = db.can_user_join_room(room_id, user_id)
    if not allowed:
        raise ApplicationError(reason)
    before = db.get_members_by_room(room_id)
    changed = not any(u == user_id and (nickname is None or n == nickname) for u, n, _ in before)
    db.add_member(user_id, room_id, nickname)
    if not restore and changed:
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


@db.atomic
def create_scenario_session(room_id, scenario, *, sync=None, expected_session_id=None):
    room_state(room_id)
    if isinstance(scenario, str):
        scenario = get_scenario_by_id(scenario)
    if scenario is None:
        raise ApplicationError("Scenario not found", 404)
    current = db.get_session_by_room(room_id)
    if current is not None and current["id"] != expected_session_id:
        fields = ("title", "context", "conflict", "opening_situation", "role_a_brief", "role_b_brief")
        if (expected_session_id is None or current["id"] > expected_session_id) and all(
            current[field] == scenario[field] for field in fields
        ):
            return current["id"]
        raise ApplicationError("Session changed; refresh before creating another session")
    if current is None and expected_session_id is not None:
        raise ApplicationError("Expected session does not exist")
    if current and db.get_pending_turn_actions(current['id'], current['current_turn']):
        raise ApplicationError('Resolve the pending turn before replacing this session')
    session_id = db.create_session_from_scenario(room_id, scenario)
    members = db.get_members_by_room(room_id)
    for member, role in zip(members, ("role_a", "role_b")):
        db.assign_role(session_id, member[0], role)
    (sync or db.bump_room_event_version)(room_id=room_id, session_id=session_id,
                                        event_type="scenario_session_created")
    return session_id


@db.atomic
def ensure_role(session_id, user_id):
    room_id = db.get_session_room_id(session_id)
    if room_id is None:
        raise ApplicationError("Session not found", 404)
    require_member(room_id, user_id)
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


def require_session_member(session_id, user_id):
    room_id = db.get_session_room_id(session_id)
    if room_id is None:
        raise ApplicationError("Session not found", 404)
    require_member(room_id, user_id)
    role = db.get_user_role(session_id, user_id)
    if role not in ("role_a", "role_b"):
        raise ApplicationError("Session participation required", 403)
    return role


def require_role_owner(session_id, user_id, role_name):
    role = require_session_member(session_id, user_id)
    if role != role_name:
        raise ApplicationError("Role ownership required", 403)
    return role


@db.atomic
def start_session(room_id, user_id, scenario_id, expected_session_id=None):
    # Recheck authorization inside the write transaction, not just in HTTP.
    require_member(room_id, user_id)
    create_scenario_session(room_id, scenario_id, expected_session_id=expected_session_id)
    return public_session(room_id)

@db.atomic
def create_room_retry_safe(user_id, request_id=None):
    if not request_id:
        return create_room(user_id, get_user_profile(user_id)['display_name'])
    import hashlib
    code = hashlib.sha256(f'{user_id}:{request_id}'.encode()).hexdigest()[:24].upper()
    existing = db.get_room_by_code(code)
    if existing:
        require_member(existing[0], user_id)
        return room_state(existing[0])
    room_id = db.create_room(code)
    db.add_member(user_id, room_id, get_user_profile(user_id)['display_name'])
    db.bump_room_event_version(room_id, 'room_created')
    return room_state(room_id)


@db.atomic
def join_by_code(code, user_id):
    room = db.get_room_by_code(code.strip().upper())
    if not room:
        raise ApplicationError('Invite code not found', 404)
    return join_room(room[0], user_id, get_user_profile(user_id)['display_name'], activate=True)


@db.atomic
def leave_room(room_id, user_id):
    room_state(room_id)
    if any(row[0] == user_id for row in db.get_members_by_room(room_id)):
        db.remove_member(user_id, room_id)
        db.bump_room_event_version(room_id, 'member_left')
    return {'status': 'left'}


@db.atomic
def update_profile(user_id, display_name, mbti='', priorities=''):
    db.save_user_profile(user_id, display_name, mbti, priorities)
    conn = db.get_connection()
    for row in conn.execute('SELECT room_id, nickname FROM members WHERE user_id=?', (user_id,)).fetchall():
        if row['nickname'] != display_name:
            db.add_member(user_id, row['room_id'], display_name)
            db.bump_room_event_version(row['room_id'], 'profile_updated')
    return get_user_profile(user_id)
