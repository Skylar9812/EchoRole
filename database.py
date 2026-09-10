import os
from pathlib import Path
import sqlite3
import json
from datetime import datetime

DB_NAME = str(Path(os.environ.get("ECHOROLE_DB_PATH", Path(__file__).resolve().with_name("echorole.db"))).expanduser().resolve())
SQLITE_TIMEOUT_SECONDS = 8.0
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_TIMEOUT_SECONDS * 1000)


def log_database_event(event, **fields):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    field_parts = []
    for key, value in fields.items():
        if value is None:
            continue
        field_parts.append(f"{key}={value!r}")

    suffix = ""
    if field_parts:
        suffix = " " + " ".join(field_parts)

    print(
        f"[EchoRole][Database][{timestamp}] event={event}{suffix}",
        flush=True
    )


def get_connection():
    conn = sqlite3.connect(
        DB_NAME,
        check_same_thread=False,
        timeout=SQLITE_TIMEOUT_SECONDS
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")

    # rooms
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invite_code TEXT UNIQUE NOT NULL,
        event_version INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("PRAGMA table_info(rooms)")
    room_columns = [row["name"] for row in cursor.fetchall()]
    if "event_version" not in room_columns:
        cursor.execute("ALTER TABLE rooms ADD COLUMN event_version INTEGER NOT NULL DEFAULT 0")

    # members
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        room_id INTEGER NOT NULL,
        nickname TEXT,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(id)
    )
    """)

    # messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        username TEXT,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        display_name TEXT,
        mbti TEXT,
        priorities TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        scenario_title TEXT,
        scenario_context TEXT,
        conflict TEXT,
        role_a_brief TEXT,
        role_b_brief TEXT,
        stages_json TEXT,
        opening_situation TEXT,
        current_stage INTEGER DEFAULT 1,
        current_situation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(id)
    )
    """)

    # 兼容旧数据库
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [row["name"] for row in cursor.fetchall()]

    if "stages_json" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN stages_json TEXT")

    if "opening_situation" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN opening_situation TEXT")

    if "current_stage" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN current_stage INTEGER DEFAULT 1")

    if "current_situation" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN current_situation TEXT")

    # session_roles
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS session_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        role_name TEXT NOT NULL,
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)
    # 创建 ai_messages 表（用户与 AI 的私有对话）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        stage_index INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        role_name TEXT NOT NULL,
        sender TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS turn_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        acting_user_id TEXT NOT NULL,
        role_name TEXT NOT NULL,
        submitted_action TEXT NOT NULL,
        resulting_situation TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_turn_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        role_name TEXT NOT NULL,
        action_text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        consumed_at TIMESTAMP DEFAULT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS turn_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        role_name TEXT NOT NULL,
        suggestion_text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS story_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        shared_situation TEXT NOT NULL,
        role_a_perspective TEXT,
        role_b_perspective TEXT,
        next_decision_point TEXT,
        role_a_brief TEXT,
        role_b_brief TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)

    cursor.execute("PRAGMA table_info(story_states)")
    story_state_columns = [row["name"] for row in cursor.fetchall()]
    if "role_a_brief" not in story_state_columns:
        cursor.execute("ALTER TABLE story_states ADD COLUMN role_a_brief TEXT")
    if "role_b_brief" not in story_state_columns:
        cursor.execute("ALTER TABLE story_states ADD COLUMN role_b_brief TEXT")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS peer_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        rater_user_id TEXT NOT NULL,
        rated_user_id TEXT NOT NULL,
        star_rating REAL NOT NULL,
        score_points INTEGER NOT NULL,
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(id),
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    """)

    # 唯一索引，避免重复数据
    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_members_user_room
    ON members(user_id, room_id)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_session_roles_user_session
    ON session_roles(session_id, user_id)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_session_roles_role_session
    ON session_roles(session_id, role_name)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_turn_history_session_turn
    ON turn_history(session_id, turn_index)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_turn_actions_session_turn_user
    ON pending_turn_actions(session_id, turn_index, user_id)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_turn_actions_session_turn_role
    ON pending_turn_actions(session_id, turn_index, role_name)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_turn_suggestions_session_turn_role
    ON turn_suggestions(session_id, turn_index, role_name)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_story_states_session_turn
    ON story_states(session_id, turn_index)
    """)

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_peer_feedback_session_rater_rated
    ON peer_feedback(session_id, rater_user_id, rated_user_id)
    """)

    conn.commit()
    conn.close()


def create_room(invite_code):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO rooms (invite_code) VALUES (?)",
        (invite_code,)
    )

    conn.commit()
    room_id = cursor.lastrowid
    conn.close()
    return room_id


def get_room_event_version(room_id):
    if not room_id:
        return 0

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COALESCE(event_version, 0) AS event_version
        FROM rooms
        WHERE id = ?
        LIMIT 1
        """,
        (room_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return 0
    return int(row["event_version"] or 0)


def bump_room_event_version(room_id, event_type, session_id=None):
    if not room_id:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            UPDATE rooms
            SET event_version = COALESCE(event_version, 0) + 1
            WHERE id = ?
            """,
            (room_id,)
        )
        cursor.execute(
            """
            SELECT COALESCE(event_version, 0) AS event_version
            FROM rooms
            WHERE id = ?
            LIMIT 1
            """,
            (room_id,)
        )
        row = cursor.fetchone()
        conn.commit()
        return int(row["event_version"] or 0) if row is not None else 0
    finally:
        conn.close()


def get_room_by_id(room_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, invite_code, created_at FROM rooms WHERE id = ?", (room_id,)
        ).fetchone()
        return tuple(row) if row else None
    finally:
        conn.close()


def get_room_by_code(invite_code):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, invite_code, created_at FROM rooms WHERE invite_code = ?",
        (invite_code,)
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None
    return (row["id"], row["invite_code"], row["created_at"])


def get_user_profile(user_id):
    if not user_id:
        return {
            "user_id": user_id,
            "display_name": "",
            "mbti": "",
            "priorities": "",
            "updated_at": None,
        }

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id, display_name, mbti, priorities, updated_at
        FROM user_profiles
        WHERE user_id = ?
        LIMIT 1
        """,
        (user_id,)
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {
            "user_id": user_id,
            "display_name": "",
            "mbti": "",
            "priorities": "",
            "updated_at": None,
        }

    return {
        "user_id": row["user_id"],
        "display_name": row["display_name"] or "",
        "mbti": row["mbti"] or "",
        "priorities": row["priorities"] or "",
        "updated_at": row["updated_at"],
    }


def save_user_profile(user_id, display_name=None, mbti=None, priorities=None):
    if not user_id:
        return

    existing = get_user_profile(user_id)
    new_display_name = existing["display_name"] if display_name is None else display_name
    new_mbti = existing["mbti"] if mbti is None else mbti
    new_priorities = existing["priorities"] if priorities is None else priorities

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO user_profiles (
            user_id, display_name, mbti, priorities, updated_at
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (user_id, new_display_name, new_mbti, new_priorities)
    )

    conn.commit()
    conn.close()


def get_peer_feedback_for_session(session_id, rater_user_id, rated_user_id):
    if not session_id or not rater_user_id or not rated_user_id:
        return None

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            room_id,
            session_id,
            rater_user_id,
            rated_user_id,
            star_rating,
            score_points,
            comment,
            created_at
        FROM peer_feedback
        WHERE session_id = ?
          AND rater_user_id = ?
          AND rated_user_id = ?
        LIMIT 1
        """,
        (session_id, rater_user_id, rated_user_id)
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "session_id": row["session_id"],
        "rater_user_id": row["rater_user_id"],
        "rated_user_id": row["rated_user_id"],
        "star_rating": float(row["star_rating"]),
        "score_points": int(row["score_points"]),
        "comment": row["comment"] or "",
        "created_at": row["created_at"],
    }


def save_peer_feedback(
    room_id,
    session_id,
    rater_user_id,
    rated_user_id,
    star_rating,
    comment=""
):
    if not room_id or not session_id or not rater_user_id or not rated_user_id:
        return None
    if rater_user_id == rated_user_id:
        return None

    normalized_rating = round(float(star_rating) * 2) / 2
    if normalized_rating < 0.5:
        normalized_rating = 0.5
    if normalized_rating > 5.0:
        normalized_rating = 5.0

    score_points = int(round(normalized_rating * 10))
    normalized_comment = str(comment or "").strip()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO peer_feedback (
                room_id,
                session_id,
                rater_user_id,
                rated_user_id,
                star_rating,
                score_points,
                comment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room_id,
                session_id,
                rater_user_id,
                rated_user_id,
                normalized_rating,
                score_points,
                normalized_comment,
            )
        )
        conn.commit()
        feedback_id = cursor.lastrowid
        log_database_event(
            "peer_feedback_saved",
            feedback_id=feedback_id,
            session_id=session_id,
            rater_user_id=rater_user_id,
            rated_user_id=rated_user_id,
            star_rating=normalized_rating,
            score_points=score_points
        )
    except sqlite3.IntegrityError:
        conn.close()
        log_database_event(
            "peer_feedback_duplicate_skipped",
            session_id=session_id,
            rater_user_id=rater_user_id,
            rated_user_id=rated_user_id
        )
        return get_peer_feedback_for_session(session_id, rater_user_id, rated_user_id)

    conn.close()
    return get_peer_feedback_for_session(session_id, rater_user_id, rated_user_id)


def get_total_received_peer_feedback_points(user_id):
    if not user_id:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COALESCE(SUM(score_points), 0) AS total_points
        FROM peer_feedback
        WHERE rated_user_id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()
    conn.close()
    if row is None:
        return 0
    return int(row["total_points"] or 0)


def add_member(user_id, room_id, nickname=None):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id FROM members
        WHERE user_id = ? AND room_id = ?
        """,
        (user_id, room_id)
    )
    existing = cursor.fetchone()

    if existing is None:
        cursor.execute(
            "INSERT INTO members (user_id, room_id, nickname) VALUES (?, ?, ?)",
            (user_id, room_id, nickname)
        )
        conn.commit()
    elif nickname is not None:
        cursor.execute(
            """
            UPDATE members
            SET nickname = ?
            WHERE user_id = ? AND room_id = ?
            """,
            (nickname, user_id, room_id)
        )
        conn.commit()

    conn.close()


def remove_member(user_id, room_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM members
        WHERE user_id = ? AND room_id = ?
        """,
        (user_id, room_id)
    )

    conn.commit()
    conn.close()


def get_members_by_room(room_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id, nickname, joined_at
        FROM members
        WHERE room_id = ?
        ORDER BY joined_at ASC, id ASC
        """,
        (room_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [(row["user_id"], row["nickname"], row["joined_at"]) for row in rows]


def can_user_join_room(room_id, user_id, max_members=2):
    if not user_id:
        return False, "Please enter a username first."

    members = get_members_by_room(room_id)
    active_member_ids = [member[0] for member in members]

    if user_id in active_member_ids:
        return True, ""

    if len(active_member_ids) >= max_members:
        return False, "This room already has two active members."

    current_session = get_session_by_room(room_id)
    if current_session is not None:
        role_rows = get_all_roles_in_session(current_session["id"])
        role_user_ids = [row[0] for row in role_rows]

        if user_id in role_user_ids:
            return True, ""

        if len(role_rows) >= max_members:
            return False, "This session already has two assigned participants."

    return True, ""


def add_message(room_id, user_id, username, content):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO messages (room_id, user_id, username, content) VALUES (?, ?, ?, ?)",
        (room_id, user_id, username, content)
    )

    conn.commit()
    conn.close()


def get_messages_by_room(room_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id, username, content, created_at
        FROM messages
        WHERE room_id = ?
        ORDER BY id ASC
        """,
        (room_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [(row["user_id"], row["username"], row["content"], row["created_at"]) for row in rows]


def get_recent_shared_chat_messages(session_id, limit=10):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT m.user_id, m.username, m.content, m.created_at
        FROM messages m
        JOIN sessions s ON s.room_id = m.room_id
        WHERE s.id = ?
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (session_id, int(limit))
    )
    rows = cursor.fetchall()
    conn.close()

    ordered_rows = list(reversed(rows))
    return [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        for row in ordered_rows
    ]


def create_session(
    room_id,
    scenario_title,
    scenario_context,
    conflict,
    role_a_brief,
    role_b_brief,
    opening_situation
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO sessions (
            room_id,
            scenario_title,
            scenario_context,
            conflict,
            role_a_brief,
            role_b_brief,
            stages_json,
            opening_situation,
            current_stage,
            current_situation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            room_id,
            scenario_title,
            scenario_context,
            conflict,
            role_a_brief,
            role_b_brief,
            json.dumps([], ensure_ascii=False),
            opening_situation,
            1,
            opening_situation
        )
    )

    conn.commit()
    session_id = cursor.lastrowid
    conn.close()
    return session_id


def create_session_from_scenario(room_id, scenario):
    return create_session(
        room_id=room_id,
        scenario_title=scenario["title"],
        scenario_context=scenario["context"],
        conflict=scenario["conflict"],
        role_a_brief=scenario["role_a_brief"],
        role_b_brief=scenario["role_b_brief"],
        opening_situation=scenario["opening_situation"]
    )


def get_session_by_room(room_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            room_id,
            scenario_title,
            scenario_context,
            conflict,
            role_a_brief,
            role_b_brief,
            opening_situation,
            current_stage,
            current_situation,
            created_at
        FROM sessions
        WHERE room_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (room_id,)
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    current_turn = row["current_stage"] if row["current_stage"] is not None else 1
    current_situation = (
        row["current_situation"]
        or row["opening_situation"]
        or row["scenario_context"]
        or row["conflict"]
        or ""
    )

    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "title": row["scenario_title"],
        "context": row["scenario_context"],
        "conflict": row["conflict"],
        "role_a_brief": row["role_a_brief"],
        "role_b_brief": row["role_b_brief"],
        "opening_situation": row["opening_situation"] or current_situation,
        "current_turn": current_turn,
        "current_situation": current_situation,
        "created_at": row["created_at"],
    }


def assign_role(session_id, user_id, role_name):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM session_roles
        WHERE session_id = ? AND user_id = ?
        """,
        (session_id, user_id)
    )
    existing = cursor.fetchone()

    if existing is None:
        cursor.execute(
            """
            INSERT INTO session_roles (session_id, user_id, role_name)
            VALUES (?, ?, ?)
            """,
            (session_id, user_id, role_name)
        )
        conn.commit()

    conn.close()


def get_user_role(session_id, user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT role_name
        FROM session_roles
        WHERE session_id = ? AND user_id = ?
        LIMIT 1
        """,
        (session_id, user_id)
    )

    row = cursor.fetchone()
    conn.close()

    if row:
        return row["role_name"]
    return None


def get_all_roles_in_session(session_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id, role_name
        FROM session_roles
        WHERE session_id = ?
        ORDER BY assigned_at ASC, id ASC
        """,
        (session_id,)
    )

    rows = cursor.fetchall()
    conn.close()
    return [(row["user_id"], row["role_name"]) for row in rows]


def get_current_turn_data(session):
    if session is None:
        return None

    return {
        "turn_index": session.get("current_turn", 1),
        "situation": session.get("current_situation", "")
    }


def get_turn_history(session_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            turn_index,
            acting_user_id,
            role_name,
            submitted_action,
            resulting_situation,
            created_at
        FROM turn_history
        WHERE session_id = ?
        ORDER BY turn_index ASC, id ASC
        """,
        (session_id,)
    )

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "turn_index": row["turn_index"],
            "acting_user_id": row["acting_user_id"],
            "role_name": row["role_name"],
            "submitted_action": row["submitted_action"],
            "resulting_situation": row["resulting_situation"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def save_pending_turn_action(session_id, turn_index, user_id, role_name, action_text):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id
            FROM pending_turn_actions
            WHERE session_id = ? AND turn_index = ? AND user_id = ?
            LIMIT 1
            """,
            (session_id, turn_index, user_id)
        )
        existing = cursor.fetchone()

        if existing is None:
            cursor.execute(
                """
                INSERT INTO pending_turn_actions (
                    session_id,
                    turn_index,
                    user_id,
                    role_name,
                    action_text,
                    status,
                    consumed_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', NULL)
                """,
                (session_id, turn_index, user_id, role_name, action_text)
            )
            row_id = cursor.lastrowid
        else:
            row_id = existing["id"]
            cursor.execute(
                """
                UPDATE pending_turn_actions
                SET role_name = ?,
                    action_text = ?,
                    status = 'pending',
                    consumed_at = NULL,
                    created_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (role_name, action_text, row_id)
            )

        conn.commit()
        return row_id
    finally:
        conn.close()


def get_pending_turn_actions(session_id, turn_index, statuses=None):
    conn = get_connection()
    cursor = conn.cursor()

    normalized_statuses = statuses or ("pending", "generating")
    placeholders = ", ".join(["?"] * len(normalized_statuses))
    query = f"""
        SELECT
            id,
            session_id,
            turn_index,
            user_id,
            role_name,
            action_text,
            status,
            created_at,
            consumed_at
        FROM pending_turn_actions
        WHERE session_id = ? AND turn_index = ? AND status IN ({placeholders})
        ORDER BY created_at ASC, id ASC
    """
    params = [session_id, turn_index, *normalized_statuses]
    cursor.execute(query, params)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "turn_index": row["turn_index"],
            "user_id": row["user_id"],
            "role_name": row["role_name"],
            "action_text": row["action_text"],
            "status": row["status"],
            "created_at": row["created_at"],
            "consumed_at": row["consumed_at"],
        }
        for row in rows
    ]


def get_pending_turn_actions_for_session_turn(session_id, turn_index, statuses=None):
    return get_pending_turn_actions(
        session_id=session_id,
        turn_index=turn_index,
        statuses=statuses or ("pending", "generating")
    )


def get_pending_turn_action_for_user(session_id, turn_index, user_id, statuses=None):
    conn = get_connection()
    cursor = conn.cursor()

    normalized_statuses = statuses or ("pending", "generating")
    placeholders = ", ".join(["?"] * len(normalized_statuses))
    query = f"""
        SELECT
            id,
            session_id,
            turn_index,
            user_id,
            role_name,
            action_text,
            status,
            created_at,
            consumed_at
        FROM pending_turn_actions
        WHERE session_id = ? AND turn_index = ? AND user_id = ? AND status IN ({placeholders})
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """
    params = [session_id, turn_index, user_id, *normalized_statuses]
    cursor.execute(query, params)

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "turn_index": row["turn_index"],
        "user_id": row["user_id"],
        "role_name": row["role_name"],
        "action_text": row["action_text"],
        "status": row["status"],
        "created_at": row["created_at"],
        "consumed_at": row["consumed_at"],
    }


def get_turn_suggestion(session_id, turn_index, role_name):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT suggestion_text
        FROM turn_suggestions
        WHERE session_id = ? AND turn_index = ? AND role_name = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id, turn_index, role_name)
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return row["suggestion_text"]


def _save_story_state_with_cursor(
    cursor,
    *,
    session_id,
    turn_index,
    shared_situation,
    role_a_perspective="",
    role_b_perspective="",
    next_decision_point="",
    role_a_brief="",
    role_b_brief=""
):
    cursor.execute(
        """
        INSERT OR REPLACE INTO story_states (
            session_id,
            turn_index,
            shared_situation,
            role_a_perspective,
            role_b_perspective,
            next_decision_point,
            role_a_brief,
            role_b_brief,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            session_id,
            turn_index,
            shared_situation,
            role_a_perspective or "",
            role_b_perspective or "",
            next_decision_point or "",
            role_a_brief or "",
            role_b_brief or "",
        )
    )
    return cursor.lastrowid


def save_story_state(
    session_id,
    turn_index,
    shared_situation,
    role_a_perspective="",
    role_b_perspective="",
    next_decision_point="",
    role_a_brief="",
    role_b_brief=""
):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        story_state_row_id = _save_story_state_with_cursor(
            cursor,
            session_id=session_id,
            turn_index=turn_index,
            shared_situation=shared_situation,
            role_a_perspective=role_a_perspective,
            role_b_perspective=role_b_perspective,
            next_decision_point=next_decision_point,
            role_a_brief=role_a_brief,
            role_b_brief=role_b_brief,
        )
        conn.commit()
        return story_state_row_id
    finally:
        conn.close()


def _row_to_story_state(row):
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "turn_index": row["turn_index"],
        "shared_situation": row["shared_situation"] or "",
        "role_a_perspective": row["role_a_perspective"] or "",
        "role_b_perspective": row["role_b_perspective"] or "",
        "next_decision_point": row["next_decision_point"] or "",
        "role_a_brief": row["role_a_brief"] or "",
        "role_b_brief": row["role_b_brief"] or "",
        "created_at": row["created_at"],
    }


def get_latest_story_state(session_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id,
            session_id,
            turn_index,
            shared_situation,
            role_a_perspective,
            role_b_perspective,
            next_decision_point,
            role_a_brief,
            role_b_brief,
            created_at
        FROM story_states
        WHERE session_id = ?
        ORDER BY turn_index DESC, id DESC
        LIMIT 1
        """,
        (session_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None
    return _row_to_story_state(row)


def get_recent_story_states(session_id, limit=3):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id,
            session_id,
            turn_index,
            shared_situation,
            role_a_perspective,
            role_b_perspective,
            next_decision_point,
            role_a_brief,
            role_b_brief,
            created_at
        FROM story_states
        WHERE session_id = ?
        ORDER BY turn_index DESC, id DESC
        LIMIT ?
        """,
        (session_id, int(limit))
    )
    rows = cursor.fetchall()
    conn.close()

    return [_row_to_story_state(row) for row in reversed(rows)]


def get_role_brief_history(session_id, role_name):
    if not session_id or role_name not in {"role_a", "role_b"}:
        return []

    brief_column = "role_a_brief" if role_name == "role_a" else "role_b_brief"
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT id, {brief_column} AS brief_text, created_at
        FROM sessions
        WHERE id = ?
        LIMIT 1
        """,
        (session_id,)
    )
    session_row = cursor.fetchone()

    cursor.execute(
        f"""
        SELECT id, turn_index, {brief_column} AS brief_text, created_at
        FROM story_states
        WHERE session_id = ?
          AND COALESCE({brief_column}, '') != ''
        ORDER BY turn_index ASC, id ASC
        """,
        (session_id,)
    )
    story_rows = cursor.fetchall()
    conn.close()

    history_entries = []
    if session_row is not None:
        original_brief = str(session_row["brief_text"] or "").strip()
        if original_brief:
            history_entries.append(
                {
                    "turn_number": 0,
                    "brief_text": original_brief,
                    "created_at": session_row["created_at"],
                }
            )

    for row in story_rows:
        brief_text = str(row["brief_text"] or "").strip()
        if brief_text == "":
            continue
        history_entries.append(
            {
                "turn_number": max(0, int(row["turn_index"] or 0) - 1),
                "brief_text": brief_text,
                "created_at": row["created_at"],
            }
        )

    return history_entries


def has_completed_turn(session_id, turn_index):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM turn_history
        WHERE session_id = ? AND turn_index = ?
        LIMIT 1
        """,
        (session_id, turn_index)
    )

    row = cursor.fetchone()
    conn.close()
    return row is not None


def claim_pending_turn_actions_for_generation(session_id, turn_index):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            SELECT id
            FROM turn_history
            WHERE session_id = ? AND turn_index = ?
            LIMIT 1
            """,
            (session_id, turn_index)
        )
        completed_row = cursor.fetchone()
        if completed_row is not None:
            conn.rollback()
            return {"status": "already_completed", "actions": None}

        cursor.execute(
            """
            SELECT
                id,
                session_id,
                turn_index,
                user_id,
                role_name,
                action_text,
                status,
                created_at,
                consumed_at
            FROM pending_turn_actions
            WHERE session_id = ? AND turn_index = ? AND status = 'pending'
            ORDER BY created_at ASC, id ASC
            """,
            (session_id, turn_index)
        )
        rows = cursor.fetchall()

        if len(rows) < 2:
            conn.rollback()
            return {"status": "waiting", "actions": None}

        actions_by_role = {
            row["role_name"]: {
                "id": row["id"],
                "session_id": row["session_id"],
                "turn_index": row["turn_index"],
                "user_id": row["user_id"],
                "role_name": row["role_name"],
                "action_text": row["action_text"],
                "status": row["status"],
                "created_at": row["created_at"],
                "consumed_at": row["consumed_at"],
            }
            for row in rows
        }

        if "role_a" not in actions_by_role or "role_b" not in actions_by_role:
            conn.rollback()
            return {"status": "waiting", "actions": None}

        cursor.execute(
            """
            UPDATE pending_turn_actions
            SET status = 'generating'
            WHERE session_id = ? AND turn_index = ? AND status = 'pending'
            """,
            (session_id, turn_index)
        )

        if cursor.rowcount < 2:
            conn.rollback()
            return {"status": "waiting", "actions": None}

        conn.commit()
        return {"status": "ready", "actions": actions_by_role}
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_pending_turn_actions_consumed(session_id, turn_index):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE pending_turn_actions
        SET status = 'consumed',
            consumed_at = CURRENT_TIMESTAMP
        WHERE session_id = ? AND turn_index = ? AND status IN ('pending', 'generating')
        """,
        (session_id, turn_index)
    )

    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected


def reset_pending_turn_actions_to_pending(session_id, turn_index):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE pending_turn_actions
        SET status = 'pending'
        WHERE session_id = ? AND turn_index = ? AND status = 'generating'
        """,
        (session_id, turn_index)
    )

    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected


def get_progression_history(session_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            scenario_title,
            scenario_context,
            conflict,
            opening_situation,
            current_stage,
            current_situation
        FROM sessions
        WHERE id = ?
        LIMIT 1
        """,
        (session_id,)
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    opening_situation = (
        row["opening_situation"]
        or row["current_situation"]
        or row["scenario_context"]
        or row["conflict"]
        or ""
    )

    return {
        "title": row["scenario_title"],
        "context": row["scenario_context"],
        "conflict": row["conflict"],
        "opening_situation": opening_situation,
        "current_turn": row["current_stage"] if row["current_stage"] is not None else 1,
        "current_situation": row["current_situation"] or opening_situation,
        "turns": get_turn_history(session_id),
    }


def add_ai_message(session_id, turn_index, user_id, role_name, sender, content):
    is_ai_reply = sender == "ai"
    content_length = len(content or "")

    if is_ai_reply:
        log_database_event(
            "add_ai_message_enter",
            session_id=session_id,
            turn_index=turn_index,
            user_id=user_id,
            role_name=role_name,
            sender=sender,
            content_length=content_length
        )

    conn = get_connection()
    cursor = conn.cursor()

    try:
        if is_ai_reply:
            log_database_event(
                "add_ai_message_before_insert",
                session_id=session_id,
                turn_index=turn_index,
                user_id=user_id,
                content_length=content_length
            )

        cursor.execute(
            """
            INSERT INTO ai_messages (
                session_id, stage_index, user_id, role_name, sender, content
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, turn_index, user_id, role_name, sender, content)
        )

        row_id = cursor.lastrowid

        if is_ai_reply:
            log_database_event(
                "add_ai_message_after_insert",
                session_id=session_id,
                turn_index=turn_index,
                user_id=user_id,
                row_id=row_id
            )
            log_database_event(
                "add_ai_message_before_commit",
                session_id=session_id,
                turn_index=turn_index,
                user_id=user_id,
                row_id=row_id
            )

        conn.commit()

        if is_ai_reply:
            log_database_event(
                "add_ai_message_after_commit",
                session_id=session_id,
                turn_index=turn_index,
                user_id=user_id,
                row_id=row_id
            )

        return row_id
    except sqlite3.Error as exc:
        try:
            conn.rollback()
            if is_ai_reply:
                log_database_event(
                    "add_ai_message_rollback_completed",
                    session_id=session_id,
                    turn_index=turn_index,
                    user_id=user_id,
                    exception_type=type(exc).__name__
                )
        except sqlite3.Error as rollback_exc:
            if is_ai_reply:
                log_database_event(
                    "add_ai_message_rollback_failed",
                    session_id=session_id,
                    turn_index=turn_index,
                    user_id=user_id,
                    rollback_exception_type=type(rollback_exc).__name__,
                    rollback_error=str(rollback_exc)
                )

        if is_ai_reply:
            log_database_event(
                "add_ai_message_sqlite_exception",
                session_id=session_id,
                turn_index=turn_index,
                user_id=user_id,
                exception_type=type(exc).__name__,
                error=str(exc)
            )
        raise
    except BaseException as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass

        if is_ai_reply:
            log_database_event(
                "add_ai_message_exception",
                session_id=session_id,
                turn_index=turn_index,
                user_id=user_id,
                exception_type=type(exc).__name__,
                error=str(exc)
            )
        raise
    finally:
        conn.close()
        if is_ai_reply:
            log_database_event(
                "add_ai_message_connection_closed",
                session_id=session_id,
                turn_index=turn_index,
                user_id=user_id
            )


def get_ai_messages(session_id, turn_index, user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT sender, content, created_at
        FROM ai_messages
        WHERE session_id = ? AND stage_index = ? AND user_id = ?
        ORDER BY id ASC
        """,
        (session_id, turn_index, user_id)
    )

    rows = cursor.fetchall()
    conn.close()
    return rows


def get_recent_ai_messages_for_user(session_id, user_id, limit=12):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            stage_index,
            role_name,
            sender,
            content,
            created_at
        FROM ai_messages
        WHERE session_id = ? AND user_id = ? AND sender IN ('user', 'ai')
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, user_id, limit)
    )

    rows = cursor.fetchall()
    conn.close()

    return list(reversed(rows))


def has_ai_prompt_for_turn(session_id, turn_index, user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM ai_messages
        WHERE session_id = ? AND stage_index = ? AND user_id = ? AND sender = 'ai'
        LIMIT 1
        """,
        (session_id, turn_index, user_id)
    )

    row = cursor.fetchone()
    conn.close()
    return row is not None


def advance_session_turn(session_id, expected_turn, new_situation):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE sessions
        SET current_stage = current_stage + 1,
            current_situation = ?
        WHERE id = ? AND current_stage = ?
        """,
        (new_situation, session_id, expected_turn)
    )

    conn.commit()
    advanced = cursor.rowcount == 1
    conn.close()
    return advanced


def complete_turn(
    session_id,
    expected_turn,
    acting_user_id,
    role_name,
    submitted_action,
    resulting_situation
):
    log_database_event(
        "complete_turn_enter",
        session_id=session_id,
        expected_turn=expected_turn,
        acting_user_id=acting_user_id,
        role_name=role_name,
        submitted_action_length=len(submitted_action or ""),
        resulting_situation_length=len(resulting_situation or "")
    )
    conn = get_connection()
    cursor = conn.cursor()

    try:
        log_database_event(
            "complete_turn_before_insert_history",
            session_id=session_id,
            expected_turn=expected_turn
        )
        cursor.execute(
            """
            INSERT INTO turn_history (
                session_id,
                turn_index,
                acting_user_id,
                role_name,
                submitted_action,
                resulting_situation
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                expected_turn,
                acting_user_id,
                role_name,
                submitted_action,
                resulting_situation
            )
        )
        log_database_event(
            "complete_turn_after_insert_history",
            session_id=session_id,
            expected_turn=expected_turn,
            history_row_id=cursor.lastrowid
        )

        log_database_event(
            "complete_turn_before_session_update",
            session_id=session_id,
            expected_turn=expected_turn
        )
        cursor.execute(
            """
            UPDATE sessions
            SET current_stage = current_stage + 1,
                current_situation = ?
            WHERE id = ? AND current_stage = ?
            """,
            (resulting_situation, session_id, expected_turn)
        )
        log_database_event(
            "complete_turn_after_session_update",
            session_id=session_id,
            expected_turn=expected_turn,
            updated_row_count=cursor.rowcount
        )

        if cursor.rowcount != 1:
            conn.rollback()
            log_database_event(
                "complete_turn_failed_session_update",
                session_id=session_id,
                expected_turn=expected_turn,
                updated_row_count=cursor.rowcount
            )
            return False

        log_database_event(
            "complete_turn_before_commit",
            session_id=session_id,
            expected_turn=expected_turn
        )
        conn.commit()
        log_database_event(
            "complete_turn_after_commit",
            session_id=session_id,
            expected_turn=expected_turn
        )
        return True
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        log_database_event(
            "complete_turn_integrity_error",
            session_id=session_id,
            expected_turn=expected_turn,
            exception_type=type(exc).__name__,
            error=str(exc)
        )
        return False
    except sqlite3.Error as exc:
        conn.rollback()
        log_database_event(
            "complete_turn_sqlite_error",
            session_id=session_id,
            expected_turn=expected_turn,
            exception_type=type(exc).__name__,
            error=str(exc)
        )
        raise
    finally:
        conn.close()
        log_database_event(
            "complete_turn_connection_closed",
            session_id=session_id,
            expected_turn=expected_turn
        )


def complete_joint_turn(
    session_id,
    expected_turn,
    submitted_action_summary,
    resulting_situation,
    role_a_perspective="",
    role_b_perspective="",
    next_decision_point="",
    role_a_brief="",
    role_b_brief="",
    role_a_suggestion="",
    role_b_suggestion=""
):
    log_database_event(
        "complete_joint_turn_enter",
        session_id=session_id,
        expected_turn=expected_turn,
        submitted_action_summary_length=len(submitted_action_summary or ""),
        resulting_situation_length=len(resulting_situation or "")
    )
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN IMMEDIATE")

        log_database_event(
            "complete_joint_turn_before_insert_history",
            session_id=session_id,
            expected_turn=expected_turn
        )
        cursor.execute(
            """
            INSERT INTO turn_history (
                session_id,
                turn_index,
                acting_user_id,
                role_name,
                submitted_action,
                resulting_situation
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                expected_turn,
                "joint_turn",
                "joint",
                submitted_action_summary,
                resulting_situation
            )
        )
        log_database_event(
            "complete_joint_turn_after_insert_history",
            session_id=session_id,
            expected_turn=expected_turn,
            history_row_id=cursor.lastrowid
        )

        log_database_event(
            "complete_joint_turn_before_session_update",
            session_id=session_id,
            expected_turn=expected_turn
        )
        cursor.execute(
            """
            UPDATE sessions
            SET current_stage = current_stage + 1,
                current_situation = ?
            WHERE id = ? AND current_stage = ?
            """,
            (resulting_situation, session_id, expected_turn)
        )
        log_database_event(
            "complete_joint_turn_after_session_update",
            session_id=session_id,
            expected_turn=expected_turn,
            updated_row_count=cursor.rowcount
        )

        if cursor.rowcount != 1:
            conn.rollback()
            log_database_event(
                "complete_joint_turn_failed_session_update",
                session_id=session_id,
                expected_turn=expected_turn,
                updated_row_count=cursor.rowcount
            )
            return False

        next_turn_index = expected_turn + 1
        story_state_row_id = _save_story_state_with_cursor(
            cursor,
            session_id=session_id,
            turn_index=next_turn_index,
            shared_situation=resulting_situation,
            role_a_perspective=role_a_perspective,
            role_b_perspective=role_b_perspective,
            next_decision_point=next_decision_point,
            role_a_brief=role_a_brief,
            role_b_brief=role_b_brief,
        )
        log_database_event(
            "complete_joint_turn_after_story_state_save",
            session_id=session_id,
            expected_turn=expected_turn,
            next_turn_index=next_turn_index,
            story_state_row_id=story_state_row_id
        )

        cursor.execute(
            """
            INSERT OR REPLACE INTO turn_suggestions (
                session_id,
                turn_index,
                role_name,
                suggestion_text,
                created_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (session_id, next_turn_index, "role_a", role_a_suggestion or "")
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO turn_suggestions (
                session_id,
                turn_index,
                role_name,
                suggestion_text,
                created_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (session_id, next_turn_index, "role_b", role_b_suggestion or "")
        )
        log_database_event(
            "complete_joint_turn_after_suggestions_save",
            session_id=session_id,
            expected_turn=expected_turn,
            next_turn_index=next_turn_index
        )

        log_database_event(
            "complete_joint_turn_before_consume_pending",
            session_id=session_id,
            expected_turn=expected_turn
        )
        cursor.execute(
            """
            UPDATE pending_turn_actions
            SET status = 'consumed',
                consumed_at = CURRENT_TIMESTAMP
            WHERE session_id = ? AND turn_index = ? AND status IN ('pending', 'generating')
            """,
            (session_id, expected_turn)
        )
        log_database_event(
            "complete_joint_turn_after_consume_pending",
            session_id=session_id,
            expected_turn=expected_turn,
            consumed_row_count=cursor.rowcount
        )

        log_database_event(
            "complete_joint_turn_before_commit",
            session_id=session_id,
            expected_turn=expected_turn
        )
        conn.commit()
        log_database_event(
            "complete_joint_turn_after_commit",
            session_id=session_id,
            expected_turn=expected_turn
        )
        return True
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        log_database_event(
            "complete_joint_turn_integrity_error",
            session_id=session_id,
            expected_turn=expected_turn,
            exception_type=type(exc).__name__,
            error=str(exc)
        )
        return False
    except sqlite3.Error as exc:
        conn.rollback()
        log_database_event(
            "complete_joint_turn_sqlite_error",
            session_id=session_id,
            expected_turn=expected_turn,
            exception_type=type(exc).__name__,
            error=str(exc)
        )
        raise
    finally:
        conn.close()
        log_database_event(
            "complete_joint_turn_connection_closed",
            session_id=session_id,
            expected_turn=expected_turn
        )


def has_ai_prompt_for_stage(session_id, stage_index, user_id):
    return has_ai_prompt_for_turn(session_id, stage_index, user_id)


def update_session_stage(session_id, new_stage):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE sessions
        SET current_stage = ?
        WHERE id = ?
        """,
        (new_stage, session_id)
    )

    conn.commit()
    conn.close()
