import sys, json, warnings, argparse, importlib.util
from pathlib import Path
parser=argparse.ArgumentParser(description='Read-only contract probes; no application or database is exercised.')
parser.add_argument('--delivery-dir', type=Path, default=Path(__file__).resolve().parent/'delivery')
parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'contract-check-results.json')
args=parser.parse_args()
local_dependencies=Path(__file__).resolve().parent/'contract-validator'
if importlib.util.find_spec('openapi_spec_validator') is None and local_dependencies.is_dir(): sys.path.insert(0,str(local_dependencies))
warnings.filterwarnings('ignore', category=DeprecationWarning)
from openapi_spec_validator import validate
from openapi_schema_validator import OAS30Validator
from jsonschema import Draft202012Validator, RefResolver
warnings.filterwarnings('ignore', category=DeprecationWarning)
api=json.loads((args.delivery_dir/'knowledge-api-v1.yaml').read_text())
snap=json.loads((args.delivery_dir/'knowledge-snapshot-schema-v1.json').read_text())
result=[]
def record(name, errors):
    result.append({'test':name,'valid':not errors,'errors':errors})
try:
    validate(api); record('OpenAPI 3.0.3 document validation',[])
except Exception as e: record('OpenAPI 3.0.3 document validation',[str(e)])
try:
    Draft202012Validator.check_schema(snap); record('Snapshot Draft202012 schema validation',[])
except Exception as e: record('Snapshot Draft202012 schema validation',[str(e)])
def check_oas(name, schema_name, obj):
    schema=api['components']['schemas'][schema_name]
    errors=[]
    try:
        for e in OAS30Validator(schema, resolver=RefResolver.from_schema(api)).iter_errors(obj):
            errors.append({'path':'/'.join(map(str,e.path)), 'message':e.message})
    except Exception as e: errors.append({'exception':type(e).__name__,'message':str(e)})
    record(name,errors)
check_oas('Unannotated problem with pending_batch=null', 'MappingSetEnvelope', {
 'error':None,'request_id':'review-test','data':{'problem_id':1,'coverage_status':'unannotated', 'approved_version':0,'next_batch_version':1,'mappings':[], 'pending_batch':None,'capabilities':['view','submit']}})
request={'request_id':'00000000-0000-4000-8000-000000000001','operation':'create','status':'pending','reason':'新增依赖','submitted_by':{'id':1,'username':'a'},'created_time':'2026-10-07T00:00:00Z','updated_time':'2026-10-07T00:00:00Z'}
check_oas('Pending create dependency response with before=null reviewed_by=null', 'DependencyChangeRequest', dict(request,before=None,reviewed_by=None,proposed={'prerequisite_code':'a','dependent_code':'b','relation_type':'required','weight':1}))
check_oas('Dependency review detail discriminator dependency_change', 'ReviewDetail', {'object_type':'dependency_change','request':request,'capabilities':[]})
check_oas('Input create without endpoint fields (should be rejected by business rule)', 'DependencyChangeRequestInput', {'operation':'create','reason':'测试'})
check_oas('Input delete with proposal field (should be rejected by business rule)', 'DependencyChangeRequestInput', {'operation':'delete','target_dependency_id':1,'base_version':1,'reason':'测试','prerequisite_code':'a'})
# basic invariants can still be delegated to service; record only, do not mistake acceptance for implementation failure.
item={'knowledge_code':'a','role':'secondary','weight':1,'source':'manual','confidence':1}
invalid_snapshot={'snapshot_type':'problem_mapping','review_batch_id':'00000000-0000-4000-8000-000000000001','problem_id':1,'batch_version':1,'base_version':0,'approved_version':1,'status':'approved','mappings':[item]}
record('Approved mapping snapshot with no primary (service must reject)', [e.message for e in Draft202012Validator(snap).iter_errors(invalid_snapshot)])
# Demonstrate that local endpoint locks are disjoint and each candidate passes acyclicity in isolation.
def cyclic(edges):
    graph={}
    for a,b in edges:graph.setdefault(a,[]).append(b)
    visiting,visited=set(),set()
    def dfs(a):
        if a in visiting:return True
        if a in visited:return False
        visiting.add(a)
        if any(dfs(b) for b in graph.get(a,[])):return True
        visiting.remove(a);visited.add(a);return False
    return any(dfs(a) for a in graph)
base=[('a','b'),('c','d')]; first=('b','c'); second=('d','a')
result.append({'test':'Concurrency counterexample (graph simulation, no DB)', 'first_candidate_cyclic':cyclic(base+[first]),'second_candidate_cyclic':cyclic(base+[second]),'endpoint_locks_disjoint':set(first).isdisjoint(second),'union_cyclic':cyclic(base+[first,second])})
# refs integrity across entire document.
refs=[]
def walk(x):
    if isinstance(x,dict):
        if '$ref' in x:refs.append(x['$ref'])
        for v in x.values():walk(v)
    elif isinstance(x,list):
        for v in x:walk(v)
walk(api)
missing=[]
for ref in refs:
    cur=api
    try:
        for part in ref.removeprefix('#/').split('/'): cur=cur[part]
    except (KeyError,TypeError):missing.append(ref)
result.append({'test':'OpenAPI local references','count':len(refs),'unresolved':missing})
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
