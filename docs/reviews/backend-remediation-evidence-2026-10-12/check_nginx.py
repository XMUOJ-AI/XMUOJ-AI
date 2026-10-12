import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path('/Users/jingweihao/大创/XMUOJ-AI')
sys.path.insert(0, str(ROOT / 'backend/deploy'))
from configure_https import configure
DOCKER = ['docker', '--context', 'colima-xmuoj-merge-20261011']
NAME = 'xmuoj-remediation-nginx-20261012'

def run(*args):
    return subprocess.run([*DOCKER, *args], check=True, capture_output=True, text=True).stdout

with tempfile.TemporaryDirectory() as directory:
    tmp = Path(directory)
    shutil.copytree(ROOT / 'backend/deploy/nginx', tmp / 'nginx')
    configure(tmp / 'nginx', {'OJ_HTTPS_MODE': 'off'})
    (tmp / 'payload.html').write_text('<script>window.synthetic=true</script>')
    (tmp / 'payload.png').write_bytes(b'PNG fixture')
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
                    '-keyout', str(tmp / 'server.key'), '-out', str(tmp / 'server.crt')], check=True, capture_output=True)
    run('create', '--name', NAME, '--add-host', 'oj-backend:127.0.0.1', '-p', '127.0.0.1:18982:8000',
        '-p', '127.0.0.1:18983:80', '--entrypoint', 'tail', 'nginx:alpine', '-f', '/dev/null')
    try:
        run('start', NAME)
        run('exec', NAME, 'mkdir', '-p', '/fixture', '/data/log', '/data/ssl', '/data/public/upload',
            '/app/data/public/upload', '/var/log/nginx')
        run('cp', str(tmp / 'nginx'), NAME + ':/fixture/nginx')
        run('cp', str(ROOT / 'frontend/deploy/nginx.conf'), NAME + ':/fixture/frontend.conf')
        for path in ('server.key', 'server.crt'):
            run('cp', str(tmp / path), NAME + ':/data/ssl/' + path)
        for base in ('/data/public/upload/', '/app/data/public/upload/'):
            for path in ('payload.html', 'payload.png'):
                run('cp', str(tmp / path), NAME + ':' + base + path)
        checks = []
        for config, port in (('/fixture/nginx/nginx.conf', 18982), ('/fixture/frontend.conf', 18983)):
            run('exec', NAME, 'nginx', '-t', '-c', config)
            run('exec', '-d', NAME, 'nginx', '-c', config)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for name, expected_type in (('payload.html', 'application/octet-stream'), ('payload.png', 'image/png')):
                with opener.open(f'http://127.0.0.1:{port}/public/upload/{name}', timeout=3) as response:
                    headers = dict(response.headers)
                    assert response.status == 200
                    assert response.headers['Content-Type'] == expected_type, headers
                    assert response.headers['X-Content-Type-Options'] == 'nosniff', headers
                    assert response.headers['Content-Security-Policy'] == 'sandbox', headers
                    checks.append({'configuration': config, 'file': name, 'status': response.status,
                                   'content_type': response.headers['Content-Type'], 'nosniff': True, 'sandbox': True})
            run('exec', NAME, 'nginx', '-s', 'stop', '-c', config)
        result = {'checks': checks, 'syntax_checks_passed': 2}
        Path('/tmp/xmuoj-remediation-20261012/nginx-results.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        run('rm', '-f', NAME)
