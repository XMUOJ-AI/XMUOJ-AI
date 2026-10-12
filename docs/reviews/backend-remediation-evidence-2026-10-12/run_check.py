import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/Users/jingweihao/大创/XMUOJ-AI')
LOG = Path('/tmp/xmuoj-remediation-20261012')
env = os.environ.copy()
env.update(json.loads(Path('/tmp/xmuoj-merge-verification/test-env.json').read_text()))
env['POSTGRES_DB'] = 'xmuoj_remediation_20261012'
kind, *args = sys.argv[1:]
if kind == 'baseline' or kind.startswith('test'):
    import psycopg2
    with psycopg2.connect(host=env['POSTGRES_HOST'], port=env['POSTGRES_PORT'], user=env['POSTGRES_USER'], password=env['POSTGRES_PASSWORD'], dbname='postgres') as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', ('test_' + env['POSTGRES_DB'],))
            if cur.fetchone():
                raise SystemExit('Refusing to run: target test database already exists.')
    cmd = ['/tmp/xmuoj-remediation-20261012/venv/bin/python', 'manage.py', 'test', *args, '--settings=oj.settings', '--noinput']
elif kind == 'migrations':
    cmd = ['/tmp/xmuoj-remediation-20261012/venv/bin/python', 'manage.py', 'makemigrations', '--check', '--dry-run', '--settings=oj.settings']
else:
    raise SystemExit('Unknown check')
started = time.monotonic()
with (LOG / f'{kind}.log').open('w') as out:
    proc = subprocess.run(cmd, cwd=ROOT / 'backend', env=env, stdout=out, stderr=subprocess.STDOUT)
result = {'check': kind, 'command': cmd, 'exit_code': proc.returncode, 'elapsed_seconds': round(time.monotonic() - started, 3)}
(LOG / f'{kind}-result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
sys.exit(proc.returncode)
