import json
import os
import re
import sys
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','oj.settings')
root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'backend'))
import django
django.setup()
import yaml
from django.test import Client, TestCase
from django.test.runner import DiscoverRunner
from openapi_schema_validator import OAS30Validator
from learning.tests import LearningFixture
from learning.models import TeachingClass, TeachingClassStudent, TeachingClassTeacher
spec=yaml.safe_load((root/'docs/openapi/learning-api-v1.yaml').read_text())
records=[]
class LearningContractProbe(LearningFixture,TestCase):
    def test_declared_responses(self):
        klass=TeachingClass.objects.create(code='contract-probe',name='Contract probe',created_by=self.author,status='active')
        TeachingClassTeacher.objects.create(teaching_class=klass,teacher=self.teacher,granted_by=self.author)
        TeachingClassStudent.objects.create(teaching_class=klass,student=self.student)
        student_path=f'/admin/learning/student/{self.student.pk}/profile'
        paths=['/learning/profile','/learning/weakness','/recommendation/path',student_path,'/admin/learning/class/knowledge-stats']
        def check(response,path,method,status):
            self.assertEqual(response.status_code,status,response.content)
            key='/admin/learning/student/{student_id}/profile' if path==student_path else path
            operation=spec['paths'][key][method]
            declared=operation['responses'][str(status)]
            if '$ref' in declared:
                declared=spec['components']['responses'][declared['$ref'].rsplit('/',1)[-1]]
            schema={**declared['content']['application/json']['schema'],'components':spec['components']}
            OAS30Validator(schema).validate(response.json())
            records.append({'method':method.upper(),'path':key,'status':status,'schema':'passed'})
        check(self.client.post('/api/recommendation/refresh','{}',content_type='application/json'),'/recommendation/refresh','post',200)
        for path in paths:
            if path.startswith('/admin/'):
                self.client.force_login(self.teacher)
            query='?class_id='+str(klass.pk) if path.startswith('/admin/') else ''
            check(self.client.get('/api'+path+query),path,'get',200)
            check(self.client.get('/api'+path+query+('&' if query else '?')+'unknown=1'),path,'get',400)
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        check(client.post('/api/recommendation/refresh','{}',content_type='application/json'),'/recommendation/refresh','post',403)
runner=DiscoverRunner(verbosity=1,interactive=False,keepdb=True)
failures=runner.run_tests(['__main__.LearningContractProbe'])
assert not failures,failures
out=root/'docs/reviews/backend-evidence-2026-10-07/learning-http-contract-probe.json'
out.write_text(json.dumps({'scope':'Django HTTP responses on real PostgreSQL test database; no external provider','responses':records},ensure_ascii=False,indent=2)+'\n')
print('Validated',len(records),'actual HTTP responses')
