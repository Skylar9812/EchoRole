"""Phase 4 browser support contracts, using disposable SQLite."""
import unittest
from backend.tests import test_stateful


class FrontendSupportTests(unittest.TestCase):
    setUp = test_stateful.StatefulTests.setUp
    profile = test_stateful.StatefulTests.profile
    def test_retry_safe_room_invite_leave_and_profile(self):
        url = '/api/v1/rooms'
        first = self.client.post(url, json={'request_id': 'stable-room'}, headers=self.auth)
        self.assertEqual(first.status_code, 201)
        room = first.json()
        self.assertEqual(self.client.post(url, json={'request_id': 'stable-room'}, headers=self.auth).json(), room)
        bob, auth = self.profile('Bob')
        joined = self.client.post(url + '/join', json={'invite_code': room['invite_code'].lower()}, headers=auth)
        self.assertEqual(joined.json()['id'], room['id'])
        session = self.client.post(f"{url}/{room['id']}/sessions", json={'scenario_id': self.scenario['id']}, headers=self.auth).json()
        changed = self.client.post('/api/v1/me', json={'display_name': 'New Bob', 'mbti': 'INTJ'}, headers=auth)
        self.assertEqual(changed.json()['display_name'], 'New Bob')
        members = self.client.get(f"{url}/{room['id']}/members", headers=self.auth).json()
        self.assertEqual(members[1]['nickname'], 'New Bob')
        leave = f"{url}/{room['id']}/leave"
        self.assertEqual(self.client.post(leave, headers=auth).status_code, 200)
        version = self.client.get(f"{url}/{room['id']}", headers=self.auth).json()['event_version']
        self.assertEqual(self.client.post(leave, headers=auth).status_code, 200)
        self.assertEqual(self.client.get(f"{url}/{room['id']}", headers=self.auth).json()['event_version'], version)
        self.assertEqual(self.client.get(f"/api/v1/sessions/{session['id']}/private", headers=auth).status_code, 403)
        self.assertEqual(self.client.post(url + '/join', json={'invite_code': room['invite_code']}, headers=auth).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/sessions/{session['id']}/private", headers=auth).status_code, 200)
        self.assertEqual(self.client.post(url + '/join', json={'invite_code': 'missing'}, headers=auth).status_code, 404)
