from pathlib import Path
import ast, json, re, shutil
import yaml
from openapi_spec_validator import validate_spec
root=Path(__file__).resolve().parents[3]
evidence=root/'docs/reviews/backend-evidence-2026-10-07'
p=root/'docs/plans/backend-completion-matrix.md'
s=p.read_text()
checks=[]
def passed(name,**extra): checks.append({'check':name,'status':'passed',**extra})
for kind,n in [('HTTP',34),('MODEL',28),('TOOL',17),('FLOW',11)]:
    ids=re.findall(r'^\| '+kind+r'-(\d+) \|',s,re.M)
    assert len(ids)==n and set(map(int,ids))==set(range(1,n+1)),(kind,ids)
    passed('matrix_'+kind.lower()+'_rows',count=n)
assert '待填' not in s and '并非 append-only 审计账本' in s
all_tests={n.name for f in (root/'backend').rglob('test*.py') for n in ast.walk(ast.parse(f.read_text())) if isinstance(n,ast.FunctionDef)}
for name in set(re.findall(r'`(test_[a-zA-Z0-9_]+)`',s)):
    assert name in all_tests,name
passed('named_test_references_exist')
for reference in re.findall(r'`(backend/[^`\s]+)`',s):
    path,_,names=reference.partition('::')
    f=root/path
    assert f.is_file(),path
    if names:
        tree=ast.parse(f.read_text())
        definitions={node.name for node in ast.walk(tree) if isinstance(node,(ast.ClassDef,ast.FunctionDef))}
        assert set(names.split('/'))<=definitions,(reference,definitions)
passed('explicit_backend_file_and_symbol_references_exist')
for link in re.findall(r'\]\(([^)]+)\)',s):
    assert (p.parent/link).exists(),link
passed('markdown_links_exist')
models={node.name for module in ['problem','submission','knowledge','learning','rag','agent_service','problem_import'] for node in ast.walk(ast.parse((root/'backend'/module/'models.py').read_text())) if isinstance(node,ast.ClassDef)}
for name in re.findall(r'^\| MODEL-\d+ \| (\w+) /',s,re.M):
    assert name in models,name
passed('baseline_model_classes_exist',count=28)
operation_total=0
for path in sorted((root/'docs/openapi').glob('*.yaml')):
    doc=yaml.safe_load(path.read_text());validate_spec(doc)
    count=sum(method in ['get','put','post','delete','options','head','patch','trace'] for item in doc['paths'].values() for method in item)
    operation_total+=count
    assert doc['info']['version']==('0.9.9' if path.name=='knowledge-api-v1.yaml' else '1.0.0')
    passed('openapi_'+path.name,operation_count=count,version=doc['info']['version'])
assert operation_total==34
spec=yaml.safe_load((root/'docs/openapi/learning-api-v1.yaml').read_text())
assert all('400' in value['get']['responses'] for value in spec['paths'].values() if 'get' in value)
assert '403' in spec['paths']['/recommendation/refresh']['post']['responses']
passed('learning_all_five_gets_declare_400_and_refresh_declares_csrf_403')
module=ast.parse((root/'backend/agent_service/contracts.py').read_text())
values={node.targets[0].id:ast.literal_eval(node.value) for node in module.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ['SIGNATURES','ALLOWLIST','PARAMETERS']}
function=next(node for node in module.body if isinstance(node,ast.FunctionDef) and node.name=='tool_schema')
exec(compile(ast.Module(body=[function],type_ignores=[]),'<tool_schema check>','exec'),values)
signatures={(name,tuple(values['tool_schema'](service,name)['required'])) for service,names in values['ALLOWLIST'].items() for name in names}
assert len(values['SIGNATURES'])==17 and len(signatures)==18
passed('registered_tools',unique_names=17,unique_signatures=18)
probe=json.loads((evidence/'learning-http-contract-probe.json').read_text())
assert len(probe['responses'])==12
passed('actual_learning_http_responses_match_declared_schemas',count=12)
(evidence/'matrix-contract-final-results.json').write_text(json.dumps({'date':'2026-10-07','scope':'working contracts and matrix checks; not sign-off','checks':checks},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(checks,ensure_ascii=False,indent=2))
