import sqlite3
import json

DB_NAME = "echorole.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # rooms
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invite_code TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

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
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO ai_messages (
            session_id, stage_index, user_id, role_name, sender, content
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, turn_index, user_id, role_name, sender, content)
    )

    conn.commit()
    conn.close()


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
    conn = get_connection()
    cursor = conn.cursor()

    try:
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

        cursor.execute(
            """
            UPDATE sessions
            SET current_stage = current_stage + 1,
                current_situation = ?
            WHERE id = ? AND current_stage = ?
            """,
            (resulting_situation, session_id, expected_turn)
        )

        if cursor.rowcount != 1:
            conn.rollback()
            return False

        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


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
