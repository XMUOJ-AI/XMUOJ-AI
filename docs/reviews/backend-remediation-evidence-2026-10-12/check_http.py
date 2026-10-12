import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

import psycopg2
from psycopg2 import sql

root = Path('/Users/jingweihao/大创/XMUOJ-AI')
out = Path('/tmp/xmuoj-remediation-20261012')
python = str(out / 'venv/bin/python')
env = os.environ.copy()
env.update(json.loads(Path('/tmp/xmuoj-merge-verification/test-env.json').read_text()))
env.update(POSTGRES_DB='xmuoj_http_round2_20261012', OJ_ENV='dev', OJ_HTTPS_MODE='off', SENTRY_DSN='')
admin = psycopg2.connect(host=env['POSTGRES_HOST'], port=env['POSTGRES_PORT'], user=env['POSTGRES_USER'],
                         password=env['POSTGRES_PASSWORD'], dbname='postgres')
admin.autocommit = True
with admin.cursor() as cursor:
    cursor.execute('SELECT 1 FROM pg_database WHERE datname=%s', (env['POSTGRES_DB'],))
    if cursor.fetchone(): raise SystemExit('Refusing to replace existing database')
    cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(env['POSTGRES_DB'])))
results = []
server = None

def record(name, detail):
    results.append({'check': name, 'passed': True, 'detail': detail})

try:
    with (out / 'http-migrate.log').open('w') as log:
        subprocess.run([python, 'manage.py', 'migrate', '--noinput'], cwd=root/'backend', env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    seed = """
import django
django.setup()
from knowledge.tests import make_user
from account.models import UserProfile
user=make_user('http-acceptance-user','Regular User','None')
user.set_password('synthetic-http-test-password')
user.save()
UserProfile.objects.create(user=user)
"""
    subprocess.run([python, 'manage.py', 'shell', '-c', seed], cwd=root/'backend', env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with (out/'gunicorn-http.log').open('w') as log:
        server = subprocess.Popen([python, '-m', 'gunicorn', 'oj.wsgi', '--bind', f'127.0.0.1:{port}',
                                   '--workers', '1', '--threads', '2', '--access-logfile', '/dev/null'],
                                  cwd=root/'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
        base = f'http://127.0.0.1:{port}'
        jar = http.cookiejar.CookieJar()
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        def request(path, body=None, csrf=None):
            headers = {'Content-Type':'application/json'}
            if csrf: headers['X-CSRFToken'] = csrf
            req = urllib.request.Request(base+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
            try:
                with client.open(req, timeout=5) as response: return response.status, response.read()
            except urllib.error.HTTPError as error: return error.code, error.read()
        deadline=time.monotonic()+20
        while True:
            try:
                status, body = request('/api/plugin/bootstrap')
                break
            except (OSError, urllib.error.URLError):
                if server.poll() is not None or time.monotonic() > deadline: raise
                time.sleep(.1)
        assert status == 200, (status, body[:120])
        data=json.loads(body)
        assert status==200 and data['data']['user'] is None
        token=data['data']['csrf_token']
        record('anonymous_bootstrap', 'HTTP 200; anonymous user; CSRF token issued')
        login={'username':'http-acceptance-user','password':'synthetic-http-test-password'}
        status,_=request('/api/plugin/login',login)
        assert status==403
        record('csrf_required', 'HTTP 403 for login without CSRF header')
        status,body=request('/api/plugin/login',login,token)
        payload=json.loads(body)
        assert status==200 and payload['error'] is None
        token2=payload['data']['csrf_token']
        assert token2 != token
        status,body=request('/api/plugin/bootstrap')
        assert status==200 and json.loads(body)['data']['user']['username']=='http-acceptance-user'
        record('session_login', 'HTTP login and subsequent Cookie-based identity; CSRF rotated')
        status,_=request('/api/plugin/logout',{},token)
        assert status==403
        record('old_csrf_rejected','HTTP 403 after login token rotation')
        status,body=request('/api/plugin/submission',[],token2)
        assert status==200 and json.loads(body)['error'] is not None
        record('invalid_json_root','Array body produces controlled API error')
        for name,headers,body in [
            ('conflicting_framing','Content-Length: 4\r\nTransfer-Encoding: chunked','0\r\n\r\n'),
            ('duplicate_content_length','Content-Length: 0\r\nContent-Length: 0','')]:
            raw=f'POST /api/plugin/login HTTP/1.1\r\nHost: 127.0.0.1\r\n{headers}\r\nConnection: close\r\n\r\n{body}'.encode()
            with socket.create_connection(('127.0.0.1',port),timeout=5) as sock:
                sock.sendall(raw); response=sock.recv(4096)
            assert response.split(b'\r\n',1)[0].startswith(b'HTTP/1.1 400'), response[:80]
            record(name,'Gunicorn rejects ambiguous framing with HTTP 400')
        status,body=request('/api/plugin/logout',{},token2)
        assert status==200 and json.loads(body)['error'] is None
        status,body=request('/api/plugin/bootstrap')
        assert json.loads(body)['data']['user'] is None
        record('session_logout', 'Session invalidated after HTTP logout')
finally:
    if server is not None:
        server.terminate()
        try:server.wait(timeout=10)
        except subprocess.TimeoutExpired:server.kill();server.wait()
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(env['POSTGRES_DB'])))
    admin.close()
    (out/'http-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results))
