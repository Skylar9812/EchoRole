"""Live transport smoke test; requires built Next.js and the backend venv.

Run from repository root: backend/.venv/Scripts/python frontend/tests/transport_smoke.py
Set ECHOROLE_NODE to an absolute Node executable when node is not on PATH.
All servers use a disposable database. No UI or provider calls.
"""
from contextlib import ExitStack
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def run():
    production = ROOT / 'echorole.db'
    before = hashlib.sha256(production.read_bytes()).digest() if production.exists() else None
    with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
        api_port, web_port = port(), port()
        origin = f'http://127.0.0.1:{web_port}'
        env = {**os.environ, 'ECHOROLE_DB_PATH': str(Path(temp) / 'transport.db'),
               'ECHOROLE_API_URL': f'http://127.0.0.1:{api_port}',
               'ECHOROLE_WEB_ORIGIN': origin, 'ECHOROLE_COOKIE_SECURE': 'false',
               'NEXT_TELEMETRY_DISABLED': '1', 'ECHOROLE_AI_PROVIDER': 'local'}
        node = os.environ.get('ECHOROLE_NODE') or shutil.which('node')
        assert node, 'Set ECHOROLE_NODE or add node to PATH'
        def start(name, command, cwd, health):
            log = stack.enter_context(open(Path(temp) / (name + '.log'), 'w+'))
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            def stop():
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
            stack.callback(stop)
            for _ in range(120):
                if process.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                try:
                    with urllib.request.urlopen(health, timeout=1) as response:
                        if response.status == 200:
                            return process
                except OSError:
                    time.sleep(.25)
            raise AssertionError(name + ' startup timeout')
        api_command = [sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', str(api_port)]
        api = start('api', api_command, ROOT, env['ECHOROLE_API_URL'] + '/api/v1/health')
        start('web', [node, 'node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', str(web_port)], ROOT / 'frontend', origin)
        jar = http.cookiejar.CookieJar()
        browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        def request(path, method='GET', body=None, browser=browser, request_origin=origin):
            req = urllib.request.Request(origin + '/api/echorole/' + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Origin': request_origin, 'Content-Type': 'application/json'}, method=method)
            try:
                response = browser.open(req, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.loads(response.read()), response.headers
        assert request('me')[0] == 401
        assert request('profiles', 'POST', {'display_name': 'Cross-site'}, request_origin='https://other.invalid')[0] == 403
        assert request('profiles', 'POST', {'display_name': 'Unprepared'})[0] == 428
        assert request('profiles/prepare', 'POST', request_origin='https://other.invalid')[0] == 403
        prepared_status, prepared_body, prepared_headers = request('profiles/prepare', 'POST')
        assert prepared_status == 200 and prepared_body == {'status': 'ready'}
        assert 'HttpOnly' in prepared_headers['Set-Cookie'] and 'SameSite=strict' in prepared_headers['Set-Cookie']
        assert 'enrollment_token' not in prepared_body
        enrollment = next(c.value for c in jar if c.name == 'echorole_enrollment')
        assert request('profiles/prepare', 'POST')[0] == 200
        assert next(c.value for c in jar if c.name == 'echorole_enrollment') == enrollment
        status, profile, headers = request('profiles', 'POST', {'display_name': 'Browser Alice'})
        assert status == 201, profile
        assert 'access_token' not in profile and 'token_type' not in profile
        cookie = headers['Set-Cookie']
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Max-Age=2592000' in cookie
        assert 'no-store' in headers['Cache-Control']
        assert request('me')[1] == profile
        assert request('profiles', 'POST', {'display_name': 'Should recover'})[1] == profile
        # Reload browser state, preserving only its cookie jar.
        refreshed = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        assert request('me', browser=refreshed)[1] == profile
        api.terminate()
        api.wait(timeout=10)
        start('api-restarted', api_command, ROOT, env['ECHOROLE_API_URL'] + '/api/v1/health')
        assert request('me', browser=refreshed)[1] == profile
        status, room, _ = request('rooms', 'POST')
        assert status == 201, room
        assert request(f'rooms/{room["id"]}')[1] == room
        assert request('rooms', 'POST', request_origin='https://other.invalid')[0] == 403
        assert request('sessions/1/private')[0] == 404
        outsider = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        assert request('profiles/prepare', 'POST', browser=outsider)[0] == 200
        assert request('profiles', 'POST', {'display_name': 'Browser Bob'}, browser=outsider)[0] == 201
        assert request(f'rooms/{room["id"]}', browser=outsider)[0] == 403
        assert request(f'rooms/{room["id"]}/join', 'POST', browser=outsider)[0] == 200
        with urllib.request.urlopen(env['ECHOROLE_API_URL'] + '/api/v1/scenarios') as catalog:
            scenario_id = json.loads(catalog.read())[0]['id']
        status, session, _ = request(f'rooms/{room["id"]}/sessions', 'POST', {'scenario_id': scenario_id})
        assert status == 201, session
        sid = session['id']
        own = request(f'sessions/{sid}/private')[1]
        other = request(f'sessions/{sid}/private', browser=outsider)[1]
        assert own['role_name'] == 'role_a' and other['role_name'] == 'role_b'
        assert own['brief'] != other['brief']
        chat = {'content': 'Live shared hello', 'request_id': 'transport-chat'}
        first_message = request(f'rooms/{room["id"]}/messages', 'POST', chat)[1]
        assert request(f'rooms/{room["id"]}/messages', 'POST', chat)[1] == first_message
        coach = request(f'sessions/{sid}/coach/messages', 'POST', {'content': 'I am worried about how to talk calmly.', 'request_id': 'transport-coach', 'turn_index': 1})
        assert coach[0] == 200 and coach[1]['state'] == 'completed', coach
        assert request(f'sessions/{sid}/coach/messages', browser=outsider)[1] == []
        assert request(f'sessions/{sid}/coach/requests')[1][0]['request_id'] == 'transport-coach'
        action = {'turn_index': 1, 'action_text': 'I will ask if we can sit down tonight and discuss our plans.'}
        waiting = request(f'sessions/{sid}/turn/actions', 'POST', action)
        assert waiting[0] == 200 and waiting[1]['state'] == 'waiting_for_other', waiting
        advanced = request(f'sessions/{sid}/turn/actions', 'POST', action, browser=outsider)
        assert advanced[0] == 200 and advanced[1]['state'] == 'advanced', advanced
        assert request(f'sessions/{sid}/turn/status?turn_index=1')[1]['state'] == 'advanced'
        assert len(request(f'sessions/{sid}/progression')[1]) == 1
        assert request(f'sessions/{sid}/suggestion')[1]['text']
        print('PASS: live shared chat, private role/Coach isolation, action waiting, turn completion, progression and suggestions')
        assert request('identity', 'DELETE')[0] == 200
        assert request('me')[0] == 401
        print('PASS: HttpOnly transport, no token in JSON, refresh and API-restart recovery, CSRF, membership, allowlist, local sign-out')
    if before is not None:
        assert hashlib.sha256(production.read_bytes()).digest() == before
        print('PASS: existing database file unchanged')


if __name__ == '__main__':
    run()
