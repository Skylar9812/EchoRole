"""Phase 2 regression/security tests. Every database and signing key is temporary."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from fastapi import Depends
from fastapi.testclient import TestClient
import application as services
import database as db
from backend.authorization import session_member, role_owner, SessionParticipant
from backend.identity import load_signing_key, TOKEN_LIFETIME
from backend.main import create_app
import test_stateful as base


class FoundationTests(unittest.TestCase):
    setUp = base.StatefulTests.setUp
    profile = base.StatefulTests.profile
    room = base.StatefulTests.room

    def test_identity_recovers_after_restart_and_preserves_profile(self):
        with TestClient(create_app()) as restarted:
            response = restarted.get('/api/v1/me', headers=self.auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {key: self.alice[key] for key in ('user_id', 'display_name', 'mbti', 'priorities')})
            self.assertNotIn('access_token', response.text)
        # A separate Python process also accepts the same credential.
        env = {**os.environ, 'ECHOROLE_DB_PATH': self.path, 'TEST_TOKEN': self.alice['access_token']}
        code = 'import os; from backend.main import create_app; from fastapi.testclient import TestClient\nwith TestClient(create_app()) as c:\n r=c.get("/api/v1/me",headers={"Authorization":"Bearer "+os.environ["TEST_TOKEN"]}); assert r.status_code==200, r.text'
        subprocess.run([sys.executable, '-c', code], env=env, check=True, capture_output=True)

    def test_missing_invalid_tampered_expired_and_deleted_identity(self):
        bob, _ = self.profile('Bob')
        token = self.alice['access_token']
        for value in ('', 'invalid', self.alice['user_id'], token + 'x', token.replace(self.alice['user_id'], bob['user_id'])):
            self.assertEqual(self.client.get('/api/v1/me', headers={'Authorization': 'Bearer ' + value}).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/me').status_code, 401)
        with patch('backend.identity.time.time', return_value=time.time() - TOKEN_LIFETIME - 1):
            _, expired = self.profile('Expired')
        self.assertEqual(self.client.get('/api/v1/me', headers=expired).status_code, 401)
        with closing(db.get_connection()) as conn:
            conn.execute('DELETE FROM user_profiles WHERE user_id = ?', (self.alice['user_id'],))
            conn.commit()
        self.assertEqual(self.client.get('/api/v1/me', headers=self.auth).status_code, 401)

    def test_signing_key_published_once_under_competing_startups(self):
        with patch.dict(os.environ, {}, clear=True):
            Path(self.path + '.identity-key').unlink(missing_ok=True)
            with ThreadPoolExecutor(max_workers=8) as pool:
                keys = list(pool.map(lambda _: load_signing_key(), range(16)))
            self.assertEqual(len(set(keys)), 1)
            self.assertEqual(len(keys[0]), 32)
            self.assertEqual(list(Path(self.path).parent.glob('*.identity-key.*')), [])

    def private_test_client(self):
        app = create_app()
        # Test-only endpoints exercise the dependencies with real private briefs.
        @app.get('/test/sessions/{session_id}/me')
        def own(p: SessionParticipant = Depends(session_member)):
            session = db.get_session_by_room(db.get_session_room_id(p.session_id))
            return {'brief': session[p.role_name + '_brief']}
        @app.get('/test/sessions/{session_id}/roles/{role_name}')
        def role(p: SessionParticipant = Depends(role_owner)):
            session = db.get_session_by_room(db.get_session_room_id(p.session_id))
            return {'brief': session[p.role_name + '_brief']}
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_session_and_role_private_authorization(self):
        rid = self.room()
        bob, bob_auth = self.profile('Bob')
        services.join_room(rid, bob['user_id'], 'Bob')
        sid = services.create_scenario_session(rid, self.scenario)
        client = self.private_test_client()
        url = f'/test/sessions/{sid}'
        own = client.get(url + '/me', headers=self.auth)
        self.assertEqual(own.json(), {'brief': self.scenario['role_a_brief']})
        self.assertNotIn(self.scenario['role_b_brief'], own.text)
        self.assertEqual(client.get(url + '/roles/role_a', headers=bob_auth).status_code, 403)
        self.assertEqual(client.get(url + '/roles/role_b', headers=bob_auth).json(), {'brief': self.scenario['role_b_brief']})
        _, other = self.profile('Outsider')
        for headers in ({}, other):
            self.assertIn(client.get(url + '/me', headers=headers).status_code, (401, 403))
        self.assertEqual(client.get('/test/sessions/999999/me', headers=self.auth).status_code, 404)
        # Even a reserved role is insufficient after leaving the room.
        db.remove_member(bob['user_id'], rid)
        self.assertEqual(client.get(url + '/me', headers=bob_auth).status_code, 403)
        services.join_room(rid, bob['user_id'], 'Bob')
        # Room membership alone cannot impersonate an old session participant.
        with closing(db.get_connection()) as conn:
            conn.execute('DELETE FROM session_roles WHERE session_id = ? AND user_id = ?', (sid, bob['user_id']))
            conn.commit()
        self.assertEqual(client.get(url + '/me', headers=bob_auth).status_code, 403)

    def test_repeated_join_does_not_duplicate_or_bump_version(self):
        rid = self.room()
        bob, auth = self.profile('Bob')
        url = f'/api/v1/rooms/{rid}/join'
        first = self.client.post(url, headers=auth).json()
        for _ in range(3):
            self.assertEqual(self.client.post(url, headers=auth).json(), first)
        self.assertEqual(len(db.get_members_by_room(rid)), 2)

    def test_session_retry_conflict_and_explicit_replacement(self):
        rid = self.room()
        url = f'/api/v1/rooms/{rid}/sessions'
        body = {'scenario_id': self.scenario['id']}
        first = self.client.post(url, headers=self.auth, json=body).json()
        for _ in range(3):
            self.assertEqual(self.client.post(url, headers=self.auth, json=body).json(), first)
        changed = {**self.scenario, 'title': 'Competing scenario'}
        with self.assertRaises(services.ApplicationError):
            services.create_scenario_session(rid, changed)
        replacement = {**body, 'expected_session_id': first['id']}
        second = self.client.post(url, headers=self.auth, json=replacement).json()
        self.assertNotEqual(second['id'], first['id'])
        self.assertEqual(self.client.post(url, headers=self.auth, json=replacement).json(), second)
        self.assertEqual(db.get_room_event_version(rid), 3)
        with closing(db.get_connection()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessions WHERE room_id = ?', (rid,)).fetchone()[0], 2)

    def test_competing_join_and_session_operations(self):
        rid = self.room()
        bob, _ = self.profile('Bob')
        charlie, _ = self.profile('Charlie')
        def join(user):
            try:
                services.join_room(rid, user['user_id'], user['display_name'])
                return 'joined'
            except services.ApplicationError:
                return 'full'
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(join, [bob, charlie] * 4))
            sessions = list(pool.map(lambda _: services.create_scenario_session(rid, self.scenario), range(8)))
        self.assertIn('full', results)
        self.assertEqual(len(db.get_members_by_room(rid)), 2)
        self.assertEqual(len(set(sessions)), 1)
        self.assertEqual(len(db.get_all_roles_in_session(sessions[0])), 2)

    def test_competing_roles_and_rollback_of_partial_session(self):
        rid = self.room()
        bob, _ = self.profile('Bob')
        services.join_room(rid, bob['user_id'], 'Bob')
        with patch.object(db, 'assign_role', side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                services.create_scenario_session(rid, self.scenario)
        self.assertIsNone(db.get_session_by_room(rid))
        self.assertEqual(db.get_room_event_version(rid), 2)
        sid = services.create_scenario_session(rid, self.scenario)
        with closing(db.get_connection()) as conn:
            conn.execute('DELETE FROM session_roles WHERE session_id = ?', (sid,))
            conn.commit()
        users = [self.alice['user_id'], bob['user_id']] * 4
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda uid: services.ensure_role(sid, uid), users))
        roles = db.get_all_roles_in_session(sid)
        self.assertEqual(len(roles), 2)
        self.assertEqual({role for _, role in roles}, {'role_a', 'role_b'})
        with self.assertRaises(db.StateConflict):
            db.assign_role(sid, roles[0][0], roles[1][1])

    def test_join_rolls_back_if_role_activation_fails(self):
        rid = self.room()
        services.create_scenario_session(rid, self.scenario)
        bob, _ = self.profile('Bob')
        before = services.room_state(rid)
        with patch.object(services, 'ensure_role', side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                services.join_room(rid, bob['user_id'], 'Bob', activate=True)
        self.assertEqual(len(db.get_members_by_room(rid)), 1)
        self.assertEqual(services.room_state(rid), before)

    def test_separate_processes_share_sqlite_serialization(self):
        rid = self.room()
        env = {**os.environ, 'ECHOROLE_DB_PATH': self.path}
        code = f'import application as s; print(s.create_scenario_session({rid}, {self.scenario["id"]!r}))'
        def run(_):
            return subprocess.run([sys.executable, '-c', code], env=env, check=True, capture_output=True, text=True).stdout.strip()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(run, range(4)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(db.get_all_roles_in_session(int(ids[0]))), 1)

    def test_busy_database_returns_retryable_error_without_partial_room(self):
        with closing(db.get_connection()) as lock:
            lock.execute('BEGIN IMMEDIATE')
            with patch.object(db, 'SQLITE_BUSY_TIMEOUT_MS', 10):
                response = self.client.post('/api/v1/rooms', headers=self.auth)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['Retry-After'], '1')
            lock.rollback()
        with closing(db.get_connection()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM rooms').fetchone()[0], 0)
