"""Phase 1 integration tests against disposable SQLite files."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import application as services
import database as db
from backend.main import create_app
from fastapi.testclient import TestClient
from scenario_library import get_scenarios_by_category, get_scenario_categories


class StatefulTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = str(Path(temp.name) / 'test.db')
        self.patch = patch.object(db, 'DB_NAME', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.scenario = get_scenarios_by_category(get_scenario_categories()[0])[0]
        self.alice, self.auth = self.profile('Alice')

    def profile(self, name):
        response = self.client.post('/api/v1/profiles', json={'display_name': name, 'mbti': 'INFJ', 'priorities': 'trust'})
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        return body, {'Authorization': 'Bearer ' + body['access_token']}

    def room(self):
        response = self.client.post('/api/v1/rooms', headers=self.auth)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def test_profile_creation_and_identity_boundary(self):
        profile = db.get_user_profile(self.alice['user_id'])
        self.assertEqual(profile['display_name'], 'Alice')
        self.assertEqual(profile['priorities'], 'trust')
        self.assertEqual(self.client.post('/api/v1/profiles', json={'display_name': '  '}).status_code, 422)
        self.assertEqual(self.client.post('/api/v1/profiles', json={'display_name': 'B', 'user_id': self.alice['user_id']}).status_code, 422)
        self.assertEqual(self.client.post('/api/v1/rooms', headers={'Authorization': 'Bearer ' + self.alice['user_id']}).status_code, 401)
        services.create_profile('Renamed', user_id=self.alice['user_id'])
        self.assertEqual(db.get_user_profile(self.alice['user_id'])['mbti'], 'INFJ')

    def test_room_join_members_lookup_and_capacity(self):
        rid = self.room()
        url = f'/api/v1/rooms/{rid}'
        room = self.client.get(url, headers=self.auth).json()
        self.assertEqual(len(room['invite_code']), 6)
        self.assertEqual(room['event_version'], 1)
        self.assertEqual(db.get_room_by_code(room['invite_code'])[0], rid)
        bob, auth = self.profile('Bob')
        self.assertEqual(self.client.get(url, headers=auth).status_code, 403)
        self.assertEqual(self.client.post(url + '/join', headers=auth).status_code, 200)
        self.assertEqual(self.client.post(url + '/join', headers=auth).status_code, 200)
        members = self.client.get(url + '/members', headers=self.auth).json()
        self.assertEqual([m['user_id'] for m in members], [self.alice['user_id'], bob['user_id']])
        _, third = self.profile('Third')
        response = self.client.post(url + '/join', headers=third)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail'], 'This room already has two active members.')
        self.assertEqual(self.client.get(url + '/session', headers=self.auth).json(), None)

    def test_session_assignment_content_and_public_privacy(self):
        rid = self.room()
        bob, auth = self.profile('Bob')
        self.client.post(f'/api/v1/rooms/{rid}/join', headers=auth)
        response = self.client.post(f'/api/v1/rooms/{rid}/sessions', headers=self.auth, json={'scenario_id': self.scenario['id']})
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()
        self.assertEqual(session['current_turn'], 1)
        self.assertEqual(session['current_situation'], self.scenario['opening_situation'])
        self.assertEqual(db.get_all_roles_in_session(session['id']), [(self.alice['user_id'], 'role_a'), (bob['user_id'], 'role_b')])
        self.assertEqual(db.get_session_by_room(rid)['role_a_brief'], self.scenario['role_a_brief'])
        expected = {'id', 'room_id', 'title', 'context', 'conflict', 'opening_situation', 'current_turn', 'current_situation', 'created_at'}
        self.assertEqual(set(session), expected)
        for suffix in ('', '/members', '/session'):
            public = self.client.get(f'/api/v1/rooms/{rid}' + suffix, headers=auth)
            self.assertEqual(public.status_code, 200)
            for private in ('role_a_brief', 'role_b_brief'):
                self.assertNotIn(private, public.text)
                self.assertNotIn(self.scenario[private], public.text)
        self.assertEqual(services.ensure_role(session['id'], bob['user_id']), 'role_b')
        self.assertEqual(len(db.get_all_roles_in_session(session['id'])), 2)

    def test_late_join_role_reservation_and_return(self):
        rid = self.room()
        sid = services.create_scenario_session(rid, self.scenario)
        bob, auth = self.profile('Bob')
        self.assertEqual(self.client.post(f'/api/v1/rooms/{rid}/join', headers=auth).status_code, 200)
        self.assertEqual(db.get_user_role(sid, bob['user_id']), 'role_b')
        db.remove_member(bob['user_id'], rid)
        _, third = self.profile('Third')
        response = self.client.post(f'/api/v1/rooms/{rid}/join', headers=third)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail'], 'This session already has two assigned participants.')
        self.assertEqual(self.client.post(f'/api/v1/rooms/{rid}/join', headers=auth).status_code, 200)
        self.assertEqual(db.get_user_role(sid, bob['user_id']), 'role_b')
        with self.assertRaises(services.ApplicationError):
            services.ensure_role(sid, 'outsider')

    def test_invalid_room_scenario_and_membership(self):
        for method, suffix, body in [('get', '', None), ('get', '/members', None), ('get', '/session', None), ('post', '/join', None), ('post', '/sessions', {'scenario_id': self.scenario['id']})]:
            response = self.client.request(method, '/api/v1/rooms/999999' + suffix, headers=self.auth, json=body)
            self.assertEqual(response.status_code, 404, response.text)
        rid = self.room()
        self.assertEqual(self.client.post(f'/api/v1/rooms/{rid}/sessions', headers=self.auth, json={'scenario_id': 'missing'}).status_code, 404)
        _, auth = self.profile('outsider')
        self.assertEqual(self.client.post(f'/api/v1/rooms/{rid}/sessions', headers=auth, json={'scenario_id': self.scenario['id']}).status_code, 403)

    def test_schema_matches_original_and_initialization_is_idempotent(self):
        original = subprocess.check_output(['git', 'show', '460c149b3ed834ec641fef65f9790f0140ec0d6c:database.py'], text=True, encoding='utf-8')
        namespace = {'__name__': 'baseline_database'}
        exec(compile(original, '<baseline>', 'exec'), namespace)
        baseline = str(Path(self.path).with_name('baseline.db'))
        namespace['DB_NAME'] = baseline
        namespace['init_db']()
        def schema(path):
            with closing(sqlite3.connect(path)) as conn:
                return conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        self.assertEqual(schema(self.path), schema(baseline))
        services.initialize()
        self.assertEqual(schema(self.path), schema(baseline))

    def test_import_from_another_directory_does_not_initialize_database(self):
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2]), 'ECHOROLE_DB_PATH': str(Path(self.path).with_name('unopened.db'))}
        code = 'import backend.main, database, pathlib, sys; assert not pathlib.Path(database.DB_NAME).exists(); assert "app" not in sys.modules; assert "ai_engine" not in sys.modules'
        subprocess.run([sys.executable, '-c', code], cwd=Path(self.path).parent, env=env, check=True)

    def test_streamlit_sync_and_restore_semantics(self):
        events = []
        def sync(**event):
            events.append(event)
            return db.bump_room_event_version(**event)
        room = services.create_room(self.alice['user_id'], 'Alice', sync=sync)
        rid = room['id']
        bob, _ = self.profile('Bob')
        services.join_room(rid, bob['user_id'], 'Bob', sync=sync)
        services.join_room(rid, bob['user_id'], 'Renamed', restore=True)
        sid = services.create_scenario_session(rid, self.scenario, sync=sync)
        self.assertEqual([event['event_type'] for event in events], ['room_created', 'member_joined', 'scenario_session_created'])
        self.assertEqual(db.get_room_event_version(rid), 3)
        self.assertEqual(db.get_members_by_room(rid)[1][1], 'Renamed')
        self.assertEqual(db.get_user_role(sid, bob['user_id']), 'role_b')
