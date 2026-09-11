"""Phase 4.5 parity and enrollment retry/security regressions, no real database."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import application as app
import database as db
from backend.main import create_app
from backend.tests import test_stateful as base


class ParityTests(unittest.TestCase):
    setUp = base.StatefulTests.setUp
    profile = base.StatefulTests.profile
    room = base.StatefulTests.room

    def test_enrollment_loss_retry_restart_concurrency_and_first_payload(self):
        with closing(db.get_connection()) as conn:
            before = conn.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0]
        token = self.client.post('/api/v1/profiles/prepare').json()['enrollment_token']
        auth = {'Authorization': 'Bearer ' + token}
        with closing(db.get_connection()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0], before)
        first = self.client.post('/api/v1/profiles', headers=auth, json={'display_name': 'Lost response', 'priorities': 'original'})
        self.assertEqual(first.status_code, 201)
        uid = first.json()['user_id']  # Ignore its access token, like a dropped response.
        with TestClient(create_app()) as restarted:
            def retry(_):
                return restarted.post('/api/v1/profiles', headers=auth, json={'display_name': 'Edited retry'}).json()
            with ThreadPoolExecutor(max_workers=6) as pool:
                replies = list(pool.map(retry, range(12)))
        self.assertEqual({r['user_id'] for r in replies}, {uid})
        self.assertEqual({r['display_name'] for r in replies}, {'Lost response'})
        with closing(db.get_connection()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0], before + 1)
        self.assertEqual(self.client.get('/api/v1/me', headers={'Authorization': 'Bearer ' + replies[0]['access_token']}).json()['user_id'], uid)
        self.assertEqual(self.client.get('/api/v1/me', headers=auth).status_code, 401)

    def test_concurrent_initial_profile_creation_uses_one_uuid(self):
        token = self.client.post('/api/v1/profiles/prepare').json()['enrollment_token']
        auth = {'Authorization': 'Bearer ' + token}
        with closing(db.get_connection()) as conn:
            before = conn.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0]
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda n: self.client.post('/api/v1/profiles', headers=auth,
                json={'display_name': f'Attempt {n}'}).json(), range(16)))
        self.assertEqual(len({r['user_id'] for r in replies}), 1)
        self.assertEqual(len({r['display_name'] for r in replies}), 1)
        with closing(db.get_connection()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0], before + 1)

    def test_enrollment_missing_tampered_expired_and_wrong_purpose(self):
        body = {'display_name': 'Invalid'}
        self.assertEqual(self.client.post('/api/v1/profiles', json=body).status_code, 401)
        token = self.client.post('/api/v1/profiles/prepare').json()['enrollment_token']
        for value in (token + 'x', self.alice['access_token'], self.alice['user_id']):
            self.assertEqual(self.client.post('/api/v1/profiles', json=body, headers={'Authorization': 'Bearer ' + value}).status_code, 401)
        with patch('backend.identity.time.time', return_value=time.time() + 31 * 86400):
            self.assertEqual(self.client.post('/api/v1/profiles', json=body, headers={'Authorization': 'Bearer ' + token}).status_code, 401)

    def setup_peer(self):
        self.rid = self.room()
        self.bob, self.bauth = self.profile('Bob')
        app.join_room(self.rid, self.bob['user_id'], 'Bob')
        self.sid = app.create_scenario_session(self.rid, self.scenario)
        self.url = f'/api/v1/sessions/{self.sid}/peer-feedback'
        self.body = {'peer_user_id': self.bob['user_id'], 'star_rating': 4.5, 'comment': '  ONLY_AUTHOR_COMMENT  '}

    def advance_for_feedback(self):
        with closing(db.get_connection()) as conn:
            conn.execute('UPDATE sessions SET current_stage=3 WHERE id=?', (self.sid,))
            conn.commit()

    def test_feedback_gate_scoring_first_write_privacy_and_leave(self):
        self.setup_peer()
        self.assertFalse(self.client.get(self.url, headers=self.auth).json()['available'])
        self.assertEqual(self.client.post(self.url, headers=self.auth, json=self.body).status_code, 409)
        self.advance_for_feedback()
        version = app.room_state(self.rid)['event_version']
        first = self.client.post(self.url, headers=self.auth, json=self.body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['feedback']['score_points'], 45)
        self.assertEqual(first.json()['feedback']['comment'], 'ONLY_AUTHOR_COMMENT')
        replay = self.client.post(self.url, headers=self.auth, json={**self.body, 'star_rating': 1, 'comment': 'changed'})
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(app.room_state(self.rid)['event_version'], version + 1)
        self.assertEqual(self.client.get('/api/v1/me/score', headers=self.bauth).json(), {'total_points': 45})
        self.assertEqual(self.client.get('/api/v1/me/score', headers=self.auth).json(), {'total_points': 0})
        self.assertNotIn('ONLY_AUTHOR_COMMENT', self.client.get(self.url, headers=self.bauth).text)
        self.assertNotIn('rater_user_id', first.text)
        outsider, auth = self.profile('Outsider')
        self.assertEqual(self.client.get(self.url, headers=auth).status_code, 403)
        self.assertEqual(self.client.post(self.url, headers=auth, json=self.body).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/me/score').status_code, 401)
        self.assertEqual(self.client.post(self.url, headers=self.bauth, json={**self.body, 'peer_user_id': self.bob['user_id']}).status_code, 409)
        app.leave_room(self.rid, self.bob['user_id'])
        self.assertFalse(self.client.get(self.url, headers=self.auth).json()['available'])
        self.assertEqual(self.client.get(self.url, headers=self.bauth).status_code, 403)

    def test_feedback_concurrency_rating_validation_and_cross_session_totals(self):
        self.setup_peer()
        self.advance_for_feedback()
        for rating in (0, 5.5, 1.3):
            self.assertEqual(self.client.post(self.url, headers=self.auth, json={**self.body, 'star_rating': rating}).status_code, 422)
        with ThreadPoolExecutor(max_workers=6) as pool:
            replies = list(pool.map(lambda _: self.client.post(self.url, headers=self.auth, json=self.body), range(10)))
        self.assertTrue(all(r.status_code == 200 for r in replies))
        self.assertEqual(app.peer_score(self.bob['user_id'])['total_points'], 45)
        with closing(db.get_connection()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM peer_feedback').fetchone()[0], 1)
        self.sid = app.create_scenario_session(self.rid, self.scenario, expected_session_id=self.sid)
        self.advance_for_feedback()
        app.submit_peer_feedback(self.sid, self.alice['user_id'], self.bob['user_id'], 0.5)
        self.assertEqual(app.peer_score(self.bob['user_id'])['total_points'], 50)
        app.submit_peer_feedback(self.sid, self.bob['user_id'], self.alice['user_id'], 5)
        self.assertEqual(app.peer_score(self.alice['user_id'])['total_points'], 50)
