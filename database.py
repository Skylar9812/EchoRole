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
        current_stage INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(id)
    )
    """)

    # 兼容旧数据库
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [row["name"] for row in cursor.fetchall()]

    if "stages_json" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN stages_json TEXT")

    if "current_stage" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN current_stage INTEGER DEFAULT 1")

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


def create_session(room_id, scenario_title, scenario_context, conflict, role_a_brief, role_b_brief, stages):
    conn = get_connection()
    cursor = conn.cursor()

    stages_json = json.dumps(stages, ensure_ascii=False)

    cursor.execute(
        """
        INSERT INTO sessions (
            room_id,
            scenario_title,
            scenario_context,
            conflict,
            role_a_brief,
            role_b_brief,
            stages_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            room_id,
            scenario_title,
            scenario_context,
            conflict,
            role_a_brief,
            role_b_brief,
            stages_json
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
        stages=scenario["stages"]
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
            stages_json,
            current_stage,
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

    stages = []
    if row["stages_json"]:
        try:
            stages = json.loads(row["stages_json"])
        except json.JSONDecodeError:
            stages = []

    return {
        "id": row["id"],
        "room_id": row["room_id"],
        "title": row["scenario_title"],
        "context": row["scenario_context"],
        "conflict": row["conflict"],
        "role_a_brief": row["role_a_brief"],
        "role_b_brief": row["role_b_brief"],
        "stages": stages,
        "current_stage": row["current_stage"],
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


def get_current_stage_data(session):
    if session is None:
        return None

    stages = session.get("stages", [])
    current_stage = session.get("current_stage", 1)

    for stage in stages:
        if stage.get("stage_index") == current_stage:
            return stage

    return None

def add_ai_message(session_id, stage_index, user_id, role_name, sender, content):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO ai_messages (
            session_id, stage_index, user_id, role_name, sender, content
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, stage_index, user_id, role_name, sender, content)
    )

    conn.commit()
    conn.close()


def get_ai_messages(session_id, stage_index, user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT sender, content, created_at
        FROM ai_messages
        WHERE session_id = ? AND stage_index = ? AND user_id = ?
        ORDER BY id ASC
        """,
        (session_id, stage_index, user_id)
    )

    rows = cursor.fetchall()
    conn.close()
    return rows


def has_ai_prompt_for_stage(session_id, stage_index, user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM ai_messages
        WHERE session_id = ? AND stage_index = ? AND user_id = ? AND sender = 'ai'
        LIMIT 1
        """,
        (session_id, stage_index, user_id)
    )

    row = cursor.fetchone()
    conn.close()
    return row is not None


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