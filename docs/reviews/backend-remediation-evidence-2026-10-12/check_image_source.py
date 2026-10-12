import hashlib
import json
from pathlib import Path
import subprocess

root=Path('/Users/jingweihao/大创/XMUOJ-AI')
out=Path('/tmp/xmuoj-remediation-20261012')
docker=['docker','--context','colima-xmuoj-merge-20261011']
expected={}
for folder,target in [('backend',''),('frontend/dist','dist/')]:
    for p in (root/folder).rglob('*'):
        relative=p.relative_to(root/folder)
        if not p.is_file() or any(part in ('data','__pycache__','.git','.DS_Store') for part in relative.parts):continue
        if p.suffix in ('.pyc','.log'):continue
        expected[target+str(relative)]=hashlib.sha256(p.read_bytes()).hexdigest()
script='''import hashlib,json,sys
from pathlib import Path
names=json.load(sys.stdin)
print(json.dumps({name:hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest() if (Path('/app')/name).is_file() else None for name in names}))
'''
result=subprocess.run([*docker,'run','--rm','-i','--network','none','--entrypoint','python','xmuoj-ai:acceptance-20261012-r2','-c',script],input=json.dumps(list(expected)),text=True,capture_output=True,check=True)
actual=json.loads(result.stdout)
mismatches=[name for name in expected if expected[name]!=actual.get(name)]
summary={'compared_files':len(expected),'mismatches':mismatches,'passed':not mismatches}
(out/'image-source-check.json').write_text(json.dumps(summary,indent=2)+'\n')
(out/'source-sha256.json').write_text(json.dumps(expected,sort_keys=True,indent=2)+'\n')
print(json.dumps(summary))
raise SystemExit(bool(mismatches))
