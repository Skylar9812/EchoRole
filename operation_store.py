"""Durable operation journal. All mutating calls must run in db.transaction()."""
import json
import time
import uuid
import database as db

# Expiration never grants another caller permission to invoke a provider.
# It only makes the uncertainty visible and allows explicit acknowledged recovery.
CLAIM_SECONDS = 900


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def get(key):
    conn = db.get_connection()
    try:
        row = conn.execute('SELECT * FROM operation_journal WHERE operation_key = ?', (key,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result['state'] == 'running' and result['started_at'] + CLAIM_SECONDS < time.time():
            result['state'] = 'uncertain'
        result['input'] = json.loads(result.pop('input_json'))
        raw = result.pop('result_json')
        result['result'] = json.loads(raw) if raw is not None else None
        return result
    finally:
        conn.close()


def insert(key, kind, scope_id, user_id, turn_index, inputs):
    attempt = str(uuid.uuid4())
    db.get_connection().execute(
        '''INSERT INTO operation_journal
        (operation_key,kind,scope_id,user_id,turn_index,state,attempt_id,started_at,input_json)
        VALUES (?,?,?,?,?,'running',?,?,?)''',
        (key, kind, scope_id, user_id, turn_index, attempt, time.time(), encode(inputs)),
    )
    return get(key)


def publish(key, attempt, result):
    # A late response may be accepted until an explicit recovery fences it off.
    cursor = db.get_connection().execute(
        "UPDATE operation_journal SET state='ready', result_json=?, error='' WHERE operation_key=? AND attempt_id=? AND state IN ('running','uncertain')",
        (encode(result), key, attempt),
    )
    return cursor.rowcount == 1


def uncertain(key, attempt):
    db.get_connection().execute(
        "UPDATE operation_journal SET state='uncertain', error='Provider outcome uncertain; explicit recovery required' WHERE operation_key=? AND attempt_id=? AND state='running'",
        (key, attempt),
    )


def complete(key):
    db.get_connection().execute("UPDATE operation_journal SET state='completed', error='' WHERE operation_key=? AND state='ready'", (key,))


def recover(key, expected_attempt):
    row = get(key)
    if not row or row['attempt_id'] != expected_attempt or row['state'] != 'uncertain':
        raise db.StateConflict('Recovery requires the current uncertain attempt')
    attempt = str(uuid.uuid4())
    db.get_connection().execute(
        "UPDATE operation_journal SET state='running', attempt_id=?, started_at=?, result_json=NULL, error='' WHERE operation_key=? AND attempt_id=?",
        (attempt, time.time(), key, expected_attempt),
    )
    return get(key)


def unfinished_coach(session_id, user_id):
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT 1 FROM operation_journal WHERE kind='coach' AND scope_id=? AND user_id=? AND state != 'completed' LIMIT 1",
            (session_id, user_id),
        ).fetchone() is not None
    finally:
        conn.close()
