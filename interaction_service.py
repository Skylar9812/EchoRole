"""Shared interactive orchestration. No HTTP/Streamlit imports or provider calls under DB locks."""
from provider_boundary import observe
import database as db
import application as app
import operation_store as journal
from coach_context import normalize_app_text as text, get_visible_ai_coach_history_entries


def engine():
    # Lazy: API import/health never initializes AI/RAG or imports app.py.
    import ai_engine
    return ai_engine


def participant(session_id, user_id, turn_index=None, *, current=False):
    role = app.require_session_member(session_id, user_id)
    session = db.get_session_by_id(session_id)
    if current and db.get_session_by_room(session['room_id'])['id'] != session_id:
        raise app.ApplicationError('Session was replaced; reload the room')
    if turn_index is not None and session['current_turn'] != turn_index:
        raise app.ApplicationError('Stale turn; reload the current turn')
    return session, role


def evolved_session(session):
    result = dict(session)
    for role in ('role_a', 'role_b'):
        history = db.get_role_brief_history(session['id'], role)
        if history:
            result[role + '_brief'] = text(history[-1]['brief_text'])
            result[role + '_brief_history_entries'] = history
    return result


@db.atomic
def private_state(session_id, user_id):
    session, role = participant(session_id, user_id)
    history = db.get_role_brief_history(session_id, role)
    story = db.get_latest_story_state(session_id)
    if not story or story['turn_index'] != session['current_turn']:
        story = {}
    return dict(session_id=session_id, turn_index=session['current_turn'], role_name=role,
                brief=text(history[-1]['brief_text'] if history else session[role + '_brief']),
                brief_history=history, pressure=text(story.get(role + '_perspective')),
                next_decision_point=text(story.get('next_decision_point')))


@db.atomic
def shared_messages(room_id, user_id):
    app.require_member(room_id, user_id)
    return db.list_room_messages(room_id)


@db.atomic
def send_chat(room_id, user_id, content, request_id):
    app.require_member(room_id, user_id)
    content = text(content).strip()
    if not content:
        raise app.ApplicationError('Message cannot be empty', 422)
    key = f'chat:{room_id}:{user_id}:{request_id}'
    old = journal.get(key)
    if old:
        if old['input']['content'] != content:
            raise app.ApplicationError('Request ID reused with different content')
        return old['result']
    claim = journal.insert(key, 'chat', room_id, user_id, 0, {'content': content})
    # Attribution comes from the authenticated profile, never request JSON.
    db.add_message(room_id, user_id, db.get_user_profile(user_id)['display_name'], content)
    result = db.list_room_messages(room_id)[-1]
    db.bump_room_event_version(room_id, 'shared_chat_message_sent')
    journal.publish(key, claim['attempt_id'], result)
    journal.complete(key)
    return result


def coach_prompt(session_id, user_id):
    session, role = participant(session_id, user_id)
    return engine().build_turn_coach_prompt(evolved_session(session), role,
        user_profile=db.get_user_profile(user_id), recent_turn_history=db.get_turn_history(session_id)[-3:])


def ensure_coach_prompt(session_id, user_id):
    session, role = participant(session_id, user_id, current=True)
    prompt = coach_prompt(session_id, user_id)
    with db.transaction():
        participant(session_id, user_id, session['current_turn'], current=True)
        if prompt and not db.has_ai_prompt_for_turn(session_id, session['current_turn'], user_id):
            db.add_ai_message(session_id, session['current_turn'], user_id, role, 'ai', prompt)
    return prompt


@db.atomic
def coach_messages(session_id, user_id, turn_index=None):
    session, _ = participant(session_id, user_id)
    turn = turn_index or session['current_turn']
    rows = db.get_ai_messages(session_id, turn, user_id)
    entries = [(turn, '', row[0], row[1], row[2]) for row in rows]
    return get_visible_ai_coach_history_entries(entries, limit=0)


@db.atomic
def suggestion(session_id, user_id):
    session, role = participant(session_id, user_id)
    # Existing product generates next-turn suggestions together with joint story.
    # There is no separate suggestion LLM/prompt to invent here.
    return dict(turn_index=session['current_turn'], text=text(db.get_turn_suggestion(session_id, session['current_turn'], role)))


@db.atomic
def progression(session_id, user_id):
    participant(session_id, user_id)
    return [{k: row[k] for k in ('turn_index', 'resulting_situation', 'created_at')}
            for row in db.get_turn_history(session_id)]


def turn_key(session_id, turn):
    return f'turn:{session_id}:{turn}'


@db.atomic
def turn_status(session_id, user_id, turn_index=None):
    session, role = participant(session_id, user_id)
    turn = turn_index or session['current_turn']
    actions = db.get_pending_turn_actions(session_id, turn, statuses=('pending','generating','consumed'))
    own = next((a for a in actions if a['user_id'] == user_id), None)
    other = any(a['user_id'] != user_id for a in actions)
    operation = journal.get(turn_key(session_id, turn))
    if turn < session['current_turn']:
        state = 'advanced'
    elif operation and operation['state'] == 'uncertain':
        state = 'uncertain'
    elif operation and operation['state'] in ('running','ready'):
        state = 'generating'
    elif own:
        state = 'submitted' if other else 'waiting_for_other'
    else:
        state = 'action_required'
    return dict(session_id=session_id, turn_index=turn, current_turn=session['current_turn'],
                state=state, submitted=own is not None, other_submitted=other,
                own_action=own['action_text'] if own else None,
                attempt_id=operation['attempt_id'] if operation else None,
                current_situation=session['current_situation'])


def submit_action(session_id, user_id, turn_index, action_text):
    action_text = text(action_text).strip()
    with db.transaction():
        session, role = participant(session_id, user_id, current=True)
        existing = db.get_pending_turn_action_for_user(session_id, turn_index, user_id, statuses=('pending','generating','consumed'))
        if turn_index != session['current_turn']:
            if turn_index < session['current_turn'] and existing and existing['action_text'] == action_text:
                return turn_status(session_id, user_id, turn_index)
            raise app.ApplicationError('Stale turn; reload the current turn')
        if existing:
            if existing['action_text'] != action_text:
                raise app.ApplicationError('Action already submitted; replacement is disabled')
        else:
            validation = engine().validate_turn_action(action_text=action_text, current_session=session, user_role=role)
            if not validation['is_valid']:
                raise app.ApplicationError(text(validation.get('feedback')) or 'Action must be concrete', 422)
            db.save_pending_turn_action(session_id, turn_index, user_id, role, action_text)
            db.bump_room_event_version(session['room_id'], 'turn_action_submitted', session_id)
    return advance_turn(session_id, user_id, turn_index)


def _claim_turn(session_id, user_id, turn_index):
    with db.transaction():
        session, _ = participant(session_id, user_id, current=True)
        key = turn_key(session_id, turn_index)
        if session['current_turn'] > turn_index:
            return None, False
        if session['current_turn'] != turn_index:
            raise app.ApplicationError('Stale turn')
        old = journal.get(key)
        if old:
            return old, False
        rows = db.get_pending_turn_actions(session_id, turn_index)
        by_role = {row['role_name']: row for row in rows}
        if not all(role in by_role for role in ('role_a','role_b')):
            return None, False
        for row in by_role.values():
            app.require_session_member(session_id, row['user_id'])
        # Freeze the same legacy inputs, with both evolved briefs deterministically.
        inputs = dict(current_session=evolved_session(session),
                      role_a_action=by_role['role_a']['action_text'], role_b_action=by_role['role_b']['action_text'],
                      recent_turn_history=db.get_turn_history(session_id)[-3:],
                      recent_shared_chat=db.get_recent_shared_chat_messages(session_id, limit=6),
                      actions=by_role)
        claim = journal.insert(key, 'turn', session_id, '', turn_index, inputs)
        if any(row['status'] == 'generating' for row in rows):
            # Pre-migration in-flight claims have no durable owner/result.
            journal.uncertain(key, claim['attempt_id'])
            return journal.get(key), False
        db.get_connection().execute("UPDATE pending_turn_actions SET status='generating' WHERE session_id=? AND turn_index=? AND status='pending'", (session_id, turn_index))
        return claim, True


def _generate(claim):
    key, attempt = claim['operation_key'], claim['attempt_id']
    inputs = dict(claim['input'])
    try:
        with observe() as outcome:
            if claim['kind'] == 'turn':
                inputs.pop('actions')
                result = engine().generate_next_situation_from_joint_actions(**inputs, debug_trace_id=attempt)
                if not isinstance(result, dict) or not text(result.get('shared_situation') or result.get('next_situation')).strip():
                    raise ValueError('Empty generation result')
            else:
                result = {'reply': text(engine().generate_dynamic_ai_feedback(**inputs, debug_trace_id=attempt))}
                if not result['reply'].strip():
                    raise ValueError('Empty Coach result')
        if outcome['uncertain']:
            raise RuntimeError('External transport outcome uncertain')
        with db.transaction():
            journal.publish(key, attempt, result)
    except Exception:
        # Timeout/errors are not evidence that a provider did no work.
        with db.transaction():
            journal.uncertain(key, attempt)
        return


@db.atomic
def _persist_turn(key):
    claim = journal.get(key)
    if not claim or claim['state'] != 'ready':
        return
    result, inputs = claim['result'], claim['input']
    sid, turn = claim['scope_id'], claim['turn_index']
    # The original CAS plus unique history/story/suggestion indexes prevent duplicates.
    persisted = db.complete_joint_turn(
        session_id=sid, expected_turn=turn,
        submitted_action_summary=f"Role A action: {inputs['role_a_action']}\n\nRole B action: {inputs['role_b_action']}",
        resulting_situation=text(result.get('shared_situation') or result.get('next_situation')),
        **{k: text(result.get(k)) for k in ('role_a_perspective','role_b_perspective','next_decision_point','role_a_suggestion','role_b_suggestion')},
        role_a_brief=text(result.get('updated_role_a_brief')), role_b_brief=text(result.get('updated_role_b_brief')),
    )
    if not persisted:
        # Legacy helper rolled back. Never commit a partial outer unit of work.
        raise app.ApplicationError('Turn could not be persisted; saved generation can be retried')
    for action in inputs['actions'].values():
        db.add_ai_message(sid, turn, action['user_id'], action['role_name'], 'action', action['action_text'])
    db.bump_room_event_version(inputs['current_session']['room_id'], 'joint_turn_progressed', sid)
    journal.complete(key)


def advance_turn(session_id, user_id, turn_index):
    claim, should_generate = _claim_turn(session_id, user_id, turn_index)
    if claim:
        if should_generate:
            _generate(claim)
        _persist_turn(claim['operation_key'])
    return turn_status(session_id, user_id, turn_index)


def recover_turn(session_id, user_id, turn_index, attempt_id, acknowledge_uncertain):
    if not acknowledge_uncertain:
        raise app.ApplicationError('Explicit acknowledgement required', 422)
    with db.transaction():
        participant(session_id, user_id, turn_index, current=True)
        claim = journal.recover(turn_key(session_id, turn_index), attempt_id)
    _generate(claim)
    _persist_turn(claim['operation_key'])
    return turn_status(session_id, user_id, turn_index)


def coach_key(session_id, user_id, request_id):
    return f'coach:{session_id}:{user_id}:{request_id}'


@db.atomic
def coach_request(session_id, user_id, request_id):
    participant(session_id, user_id)
    claim = journal.get(coach_key(session_id, user_id, request_id))
    if not claim:
        raise app.ApplicationError('Coach request not found', 404)
    return dict(request_id=request_id, turn_index=claim['turn_index'], state=claim['state'],
                attempt_id=claim['attempt_id'], reply=(claim['result'] or {}).get('reply') if claim['state']=='completed' else None)


@db.atomic
def _persist_coach(key):
    claim = journal.get(key)
    if not claim or claim['state'] != 'ready':
        return
    db.add_ai_message(claim['scope_id'], claim['turn_index'], claim['user_id'], claim['input']['user_role'], 'ai', claim['result']['reply'])
    journal.complete(key)


def send_coach(session_id, user_id, turn_index, content, request_id):
    content = text(content).strip()
    if not content:
        raise app.ApplicationError('AI reply cannot be empty', 422)
    participant(session_id, user_id)  # Completed retries may recover an earlier turn's reply.
    key = coach_key(session_id, user_id, request_id)
    old = journal.get(key)
    if not old:
        ensure_coach_prompt(session_id, user_id)
    with db.transaction():
        old = journal.get(key)
        if old:
            if old['input']['user_text'] != content or old['turn_index'] != turn_index:
                raise app.ApplicationError('Request ID reused with different content or turn')
            claim, should_generate = old, False
        else:
            session, role = participant(session_id, user_id, turn_index, current=True)
            if journal.unfinished_coach(session_id, user_id):
                raise app.ApplicationError('Resolve the previous Coach request first')
            history = get_visible_ai_coach_history_entries(db.get_recent_ai_messages_for_user(session_id, user_id, limit=16), limit=8)
            story = db.get_latest_story_state(session_id)
            situation = text(story['shared_situation'] if story and story['turn_index']==turn_index else session['current_situation'])
            inputs = dict(user_role=role, user_text=content, current_turn=turn_index,
                          current_situation=situation, current_session=session,
                          user_profile=db.get_user_profile(user_id), recent_turn_history=db.get_turn_history(session_id)[-3:], recent_coach_history=history)
            claim = journal.insert(key, 'coach', session_id, user_id, turn_index, inputs)
            db.add_ai_message(session_id, turn_index, user_id, role, 'user', content)
            should_generate = True
    if should_generate:
        _generate(claim)
    _persist_coach(key)
    return coach_request(session_id, user_id, request_id)


def recover_coach(session_id, user_id, request_id, attempt_id, acknowledge_uncertain):
    if not acknowledge_uncertain:
        raise app.ApplicationError('Explicit acknowledgement required', 422)
    with db.transaction():
        participant(session_id, user_id)
        claim = journal.recover(coach_key(session_id, user_id, request_id), attempt_id)
    _generate(claim)
    _persist_coach(claim['operation_key'])
    return coach_request(session_id, user_id, request_id)


@db.atomic
def pending_coach_request(session_id, user_id):
    participant(session_id, user_id)
    with db.transaction():
        row = db.get_connection().execute(
            "SELECT operation_key FROM operation_journal WHERE kind='coach' AND scope_id=? AND user_id=? AND state!='completed' ORDER BY started_at LIMIT 1",
            (session_id, user_id),
        ).fetchone()
    if row:
        return coach_request(session_id, user_id, row['operation_key'].split(':')[-1])
    return None


def persist_coach_request(session_id, user_id, request_id):
    participant(session_id, user_id)
    _persist_coach(coach_key(session_id, user_id, request_id))
    return coach_request(session_id, user_id, request_id)


@db.atomic
def coach_requests(session_id, user_id):
    participant(session_id, user_id)
    conn = db.get_connection()
    try:
        keys = [r[0] for r in conn.execute(
            "SELECT operation_key FROM operation_journal WHERE kind='coach' AND scope_id=? AND user_id=? ORDER BY started_at",
            (session_id, user_id),
        ).fetchall()]
    finally:
        conn.close()
    return [coach_request(session_id, user_id, key.split(':')[-1]) for key in keys]
