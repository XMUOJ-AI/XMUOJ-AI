"""Isolated rollback rehearsal. Never drops databases or writes to the source.

Run from the repository root with .venv/bin/python. First run `clone-plan`, inspect
migration-rollback-plan.txt, then run `exercise`. The fixed clone must not exist
at creation; remove/rename nothing automatically. Requires local Docker PG14.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CONTAINER = 'xmuoj-ai-test-postgres-20261007'
SOURCE, TARGET = 'onlinejudge', 'xmuoj_rollback'
MARKER = OUT / 'migration-rollback-results.json'
ENV = {'OJ_ENV': 'dev', 'DJANGO_SETTINGS_MODULE': 'oj.settings',
       'POSTGRES_HOST': '127.0.0.1', 'POSTGRES_PORT': '15432',
       'POSTGRES_DB': TARGET, 'POSTGRES_USER': 'onlinejudge', 'REDIS_PORT': '16379'}
NEW_APPS = ('knowledge', 'learning', 'agent_service', 'rag', 'problem_import')
LEGACY_TARGETS = [('account', '0012_userprofile_language'),
                  ('problem', '0015_problem_tag_governance'),
                  ('submission', '0012_auto_20180501_0436'),
                  ('contest', '0012_contestparticipation_calibration'),
                  ('options', '0003_migrate_languages_options')]

def command(args, **kwargs):
    print('$', ' '.join(map(str, args)), flush=True)
    return subprocess.run(args, check=True, **kwargs)

def docker(*args, **kwargs):
    return command(['docker', 'exec', CONTAINER, *args], **kwargs)

def save(data):
    MARKER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

def source_summary():
    query = "SELECT app || '.' || name FROM django_migrations ORDER BY app,name"
    migrations = subprocess.check_output(['docker', 'exec', CONTAINER, 'psql', '-U', 'onlinejudge', '-d', SOURCE,
                                          '-X', '-Atc', query], text=True).splitlines()
    query = "SELECT 'users=' || count(*) FROM public.user UNION ALL SELECT 'problems=' || count(*) FROM problem"
    counts = subprocess.check_output(['docker', 'exec', CONTAINER, 'psql', '-U', 'onlinejudge', '-d', SOURCE,
                                      '-X', '-Atc', query], text=True).splitlines()
    return {'migrations': migrations, 'legacy_row_counts': counts}

def connect():
    os.environ.update(ENV)
    sys.path.insert(0, str(ROOT / 'backend'))
    import django
    django.setup()
    from django.db import connection
    assert connection.settings_dict['NAME'] == TARGET
    assert connection.settings_dict['HOST'] == '127.0.0.1'
    assert str(connection.settings_dict['PORT']) == '15432'
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database(), version()')
        name, version = cursor.fetchone()
    assert name == TARGET and 'PostgreSQL 14.' in version, (name, version)
    print('GUARD: migration executor connected exclusively to', name, version.split(' on ')[0], flush=True)
    return connection

def executor(connection):
    from django.db.migrations.executor import MigrationExecutor
    return MigrationExecutor(connection)

def describe_plan(engine, targets):
    return [{'migration': f'{m.app_label}.{m.name}', 'backwards': backwards,
             'operations': [op.describe() for op in m.operations]} for m, backwards in engine.migration_plan(targets)]

def targets():
    return [(app, None) for app in NEW_APPS] + LEGACY_TARGETS

def state_apps(connection):
    return executor(connection).loader.project_state().apps

def triggers(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'knowledge_%' ORDER BY tgname")
        return [row[0] for row in cursor.fetchall()]

def assert_guard(connection, user_id, label):
    from django.db import IntegrityError, transaction
    Event = state_apps(connection).get_model('knowledge', 'KnowledgeReviewEvent')
    event = Event.objects.create(object_type='knowledge_point', object_key='rollback_probe', object_version=1,
                                 action='deleted', actor_id=user_id, snapshot={'probe': label}, request_id=label)
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('UPDATE knowledge_review_event SET reason=%s WHERE id=%s', ['must fail', event.pk])
    except IntegrityError as exc:
        assert getattr(exc.__cause__, 'pgcode', None) == '23514'
        print(label, 'trigger rejected UPDATE with SQLSTATE 23514', flush=True)
    else:
        raise AssertionError('append-only trigger did not reject UPDATE')
    assert Event.objects.get(pk=event.pk).reason == ''


def clone_plan():
    binding = subprocess.check_output(['docker', 'port', CONTAINER, '5432/tcp'], text=True).strip()
    assert binding == '127.0.0.1:15432', binding
    exists = subprocess.check_output(['docker', 'exec', CONTAINER, 'psql', '-U', 'onlinejudge', '-d', 'postgres',
                                     '-X', '-Atc', "SELECT datname FROM pg_database WHERE datname='xmuoj_rollback'"], text=True).strip()
    assert not exists, 'Refusing to reuse or drop an existing xmuoj_rollback database'
    assert not MARKER.exists(), 'Refusing to overwrite prior rehearsal evidence'
    data = {'source': SOURCE, 'clone': TARGET, 'container': CONTAINER, 'binding': binding,
            'source_before': source_summary(), 'checks': [], 'status': 'creating_clone'}
    archive = Path(tempfile.mkdtemp(prefix='xmuoj-rollback-20261007-')) / 'onlinejudge.dump'
    with archive.open('wb') as output:
        docker('pg_dump', '-U', 'onlinejudge', '-d', SOURCE, '--format=custom', '--no-owner', '--no-acl', stdout=output)
    archive.chmod(0o600)
    data['backup'] = {'path': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'bytes': archive.stat().st_size}
    save(data)
    docker('createdb', '-U', 'onlinejudge', '--template=template0', TARGET)
    with archive.open('rb') as source:
        command(['docker', 'exec', '-i', CONTAINER, 'pg_restore', '-U', 'onlinejudge', '-d', TARGET,
                 '--no-owner', '--no-acl', '--exit-on-error'], stdin=source)
    connection = connect()
    try:
        engine = executor(connection)
        data['leaf_nodes'] = sorted(engine.loader.graph.leaf_nodes())
        plan = describe_plan(engine, targets())
        assert plan and all(row['backwards'] for row in plan)
        assert all(row['migration'].split('.')[0] in {*NEW_APPS, *(x[0] for x in LEGACY_TARGETS)} for row in plan)
        assert all(m.reversible for migration, _ in engine.migration_plan(targets()) for m in migration.operations)
        data['rollback_plan'] = plan
        data['learning_rename_plan'] = describe_plan(engine, [('learning', '0001_initial')])
        data['knowledge_guard_plan'] = describe_plan(engine, [('knowledge', '0001_initial')])
        data['new_tables'] = sorted(model._meta.db_table for app in NEW_APPS
                                   for model in engine.loader.project_state().apps.get_app_config(app).get_models())
        data['status'] = 'clone_restored_plan_ready'
        data['checks'].append({'name': 'custom_dump_restore_new_clone', 'status': 'passed'})
        save(data)
        (OUT / 'migration-rollback-plan.txt').write_text(json.dumps({k: data[k] for k in ['clone', 'binding', 'leaf_nodes', 'rollback_plan', 'learning_rename_plan', 'knowledge_guard_plan']}, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'clone': TARGET, 'reverse_migrations': [x['migration'] for x in plan],
                          'new_table_count': len(data['new_tables']), 'status': data['status']}, ensure_ascii=False, indent=2), flush=True)
    finally:
        connection.close()


def exercise():
    data = json.loads(MARKER.read_text())
    assert data['status'] == 'clone_restored_plan_ready'
    assert data['clone'] == TARGET and data['source'] == SOURCE
    connection = connect()
    try:
        engine = executor(connection)
        assert describe_plan(engine, targets()) == data['rollback_plan'], 'Migration graph changed since plan inspection'
        apps = state_apps(connection)
        User, Problem = apps.get_model('account', 'User'), apps.get_model('problem', 'Problem')
        Point, Rating = apps.get_model('knowledge', 'KnowledgePoint'), apps.get_model('learning', 'ProblemKnowledgeRating')
        user = User.objects.create(username='rollback_only_probe', password='!', session_keys=['rollback_probe'])
        problem = Problem.objects.create(_id='ROLLBACK_ONLY_PROBE', title='Rollback fixture', description='Fixture',
                                         input_description='Fixture', output_description='Fixture', samples=[{'input': '1', 'output': '1'}],
                                         test_case_id='rollback_probe_no_files', test_case_score=[], languages=['Python3'], template={},
                                         created_by_id=user.pk, time_limit=1000, memory_limit=128, rule_type='ACM', difficulty='Low')
        point = Point.objects.create(code='rollback_only_probe', name='Rollback fixture', normalized_name='rollback fixture',
                                     category='algorithm', level=1, status='active', created_by_id=user.pk)
        rating = Rating.objects.create(problem_id=problem.pk, knowledge_point_id=point.pk, attempt_count=7,
                                       accepted_count=3, rating='1234.5678', confidence='0.750')
        assert_guard(connection, user.pk, 'before_reverse')
        engine = executor(connection)
        assert [(m.app_label, m.name) for m, backwards in engine.migration_plan([('learning', '0001_initial')]) if backwards] == [('learning', '0002_align_learning_contract')]
        engine.migrate([('learning', '0001_initial')])
        with connection.cursor() as cursor:
            cursor.execute('SELECT sample_count,accepted_count,rating,confidence FROM problem_knowledge_rating WHERE id=%s', [rating.pk])
            old = cursor.fetchone()
        assert tuple(map(str, old)) == ('7', '3', '1234.5678', '0.750'), old
        executor(connection).migrate([('learning', '0002_align_learning_contract')])
        with connection.cursor() as cursor:
            cursor.execute('SELECT attempt_count,accepted_count,rating,confidence FROM problem_knowledge_rating WHERE id=%s', [rating.pk])
            new = cursor.fetchone()
        assert old == new
        data['checks'].append({'name': 'learning_0002_reverse_and_forward_preserves_rating_row', 'status': 'passed',
                               'values': list(map(str, new)), 'scope': 'one representative populated rating row; not all migration data'})
        print('PASS learning0002 rename reverse+upgrade retained count/rating/confidence', list(map(str, new)), flush=True)
        executor(connection).migrate(targets())
        present = set(connection.introspection.table_names())
        assert not present.intersection(data['new_tables']), present.intersection(data['new_tables'])
        assert triggers(connection) == []
        data['checks'].append({'name': 'new_apps_and_legacy_reconciliation_reversed', 'status': 'passed',
                               'new_tables_absent': len(data['new_tables']), 'data_loss': 'All new module tables and their rows removed; contest.is_exam also removed'})
        print('PASS full reverse: new tables absent =', len(data['new_tables']), '; knowledge triggers absent', flush=True)
        executor(connection).migrate([tuple(x) for x in data['leaf_nodes']])
        engine = executor(connection)
        assert not engine.migration_plan(engine.loader.graph.leaf_nodes())
        assert set(data['new_tables']) <= set(connection.introspection.table_names())
        assert len(triggers(connection)) == 3, triggers(connection)
        apps = state_apps(connection)
        assert apps.get_model('learning', 'ProblemKnowledgeRating').objects.count() == 0
        assert apps.get_model('account', 'User').objects.get(pk=user.pk).session_keys == ['rollback_probe']
        assert apps.get_model('problem', 'Problem').objects.get(pk=problem.pk).samples == [{'input': '1', 'output': '1'}]
        assert_guard(connection, user.pk, 'after_upgrade')
        data['checks'].append({'name': 'leaf_upgrade_tables_and_triggers_restored', 'status': 'passed',
                               'legacy_probe_json_preserved': True, 'removed_new_module_data_restored': False})
        from django.core.management import call_command
        call_command('check', verbosity=1)
        call_command('makemigrations', check=True, dry_run=True, verbosity=1)
        data['checks'].append({'name': 'django_check_and_no_model_migration_drift', 'status': 'passed'})
        data['source_after'] = source_summary()
        assert data['source_before'] == data['source_after'], 'Source summary changed during rehearsal; investigate separately'
        data['checks'].append({'name': 'source_migration_and_legacy_counts_unchanged', 'status': 'passed',
                               'scope': 'migration list and User/Problem counts; source never used for writes by this script'})
        data['status'] = 'passed_with_explicit_destructive_reverse_boundary'
        save(data)
        print(json.dumps(data['checks'], ensure_ascii=False, indent=2), flush=True)
    finally:
        from django.db import connections
        connections.close_all()
        print('Closed all Django connections to rollback clone', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('clone-plan', 'exercise'))
    args = parser.parse_args()
    (clone_plan if args.stage == 'clone-plan' else exercise)()
