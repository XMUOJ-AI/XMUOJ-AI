import json
import os
from pathlib import Path
import subprocess
import time

import psycopg2
from psycopg2 import sql

root = Path('/Users/jingweihao/大创/XMUOJ-AI')
out = Path('/tmp/xmuoj-remediation-20261012')
env = os.environ.copy()
env.update(json.loads(Path('/tmp/xmuoj-merge-verification/test-env.json').read_text()))
database = 'xmuoj_upgrade_round2_20261012'
env['POSTGRES_DB'] = database
env['DJANGO_SETTINGS_MODULE'] = 'oj.settings'
old_python = str(root / '.venv/bin/python')
new_python = str(out / 'venv/bin/python')
before = out / 'before-upgrade/backend'
admin = psycopg2.connect(host=env['POSTGRES_HOST'], port=env['POSTGRES_PORT'],
                         user=env['POSTGRES_USER'], password=env['POSTGRES_PASSWORD'], dbname='postgres')
admin.autocommit = True
with admin.cursor() as cursor:
    cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (database,))
    if cursor.fetchone():
        raise SystemExit('Refusing to replace an existing database')
    cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
results = []


def run(name, python, cwd, args):
    started = time.monotonic()
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run([python, *args], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    results.append({'check': name, 'exit_code': result.returncode, 'elapsed_seconds': round(time.monotonic() - started, 3)})
    if result.returncode:
        raise RuntimeError(name + ' failed; see its log')


seed = '''
import django
django.setup()
from datetime import timedelta
from django.utils import timezone
from account.models import UserProfile
from knowledge.tests import make_user, make_problem
from contest.models import Contest, ContestParticipation
from submission.models import Submission, JudgeStatus
owner = make_user('upgrade-owner')
student = make_user('upgrade-student', 'Regular User', 'None')
student.set_password('synthetic-upgrade-password')
student.save()
UserProfile.objects.create(user=student)
contest = Contest.objects.create(title='upgrade-fixture', description='preserve-me', rule_type='OI', real_time_rank=True, created_by=owner,
    start_time=timezone.now()-timedelta(hours=1), end_time=timezone.now()+timedelta(hours=1))
problem = make_problem(owner, 'UPGRADE-1')
problem.contest, problem.rule_type = contest, 'OI'
problem.save()
Submission.objects.create(user_id=student.pk, username=student.username, problem=problem, contest=contest,
    language='Python3', code='print(1)', result=JudgeStatus.ACCEPTED, statistic_info={'score':100,'preserve':'中文'})
ContestParticipation.objects.create(user=student, contest=contest)
print('Synthetic legacy user/password hash, contest, problem, JSON verdict and participation inserted.')
'''
verify = '''
import django
django.setup()
from django.db import connection
from account.models import User
from contest.models import Contest, ContestParticipation
from submission.models import Submission
student = User.objects.get(username='upgrade-student')
assert student.check_password('synthetic-upgrade-password')
contest = Contest.objects.get(title='upgrade-fixture')
assert contest.description == 'preserve-me'
submission = Submission.objects.get(user_id=student.pk)
assert submission.statistic_info == {'score':100,'preserve':'中文'} and submission.code == 'print(1)'
assert ContestParticipation.objects.filter(user=student, contest=contest).count() == 1
with connection.cursor() as cursor:
    constraints = connection.introspection.get_constraints(cursor, 'contest_participation')
assert constraints['contest_part_user_enter_idx']['columns'] == ['user_id','last_enter_time']
print('Legacy rows, old password verification, JSON data and renamed index preserved.')
'''
try:
    run('upgrade-old-migrate', old_python, before, ['manage.py','migrate','--noinput'])
    run('upgrade-seed', old_python, before, ['-c',seed])
    run('upgrade-new-migrate', new_python, root/'backend', ['manage.py','migrate','--noinput'])
    run('upgrade-preservation', new_python, root/'backend', ['-c',verify])
    run('migration-drift', new_python, root/'backend', ['manage.py','makemigrations','--check','--dry-run'])
    run('system-check', new_python, root/'backend', ['manage.py','check'])
    run('migration-plan', new_python, root/'backend', ['manage.py','migrate','--plan'])
finally:
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
    admin.close()
    (out/'upgrade-results.json').write_text(json.dumps(results, indent=2)+'\n')
print(json.dumps(results))
