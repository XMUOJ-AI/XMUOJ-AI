"""Verify production source bytes in the built image before entrypoint mutations."""
import hashlib
import json
from pathlib import Path
import subprocess
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EVIDENCE = ROOT / "docs/reviews/backend-h1-h7-evidence-2026-10-07/h6-h7"
paths = set(json.loads((HERE / "source-hashes.json").read_text()))
paths.update(str(p.relative_to(ROOT / "backend")) for p in (ROOT / "backend/conf/migrations").glob("*.py"))
manifest = {name: hashlib.sha256((ROOT / "backend" / name).read_bytes()).hexdigest() for name in sorted(paths)}
(EVIDENCE / "source-sha256.json").write_text(json.dumps(manifest, indent=2))
code = "import hashlib,json,sys; from pathlib import Path; m=json.load(sys.stdin); bad=[p for p,h in m.items() if not Path('/app',p).is_file() or hashlib.sha256(Path('/app',p).read_bytes()).hexdigest()!=h]; print(json.dumps({'checked_files':len(m),'mismatches':bad})); sys.exit(bool(bad))"
result = subprocess.run(["docker", "run", "--rm", "-i", "--entrypoint", "python", "xmuoj-ai:h1-h7-20261007", "-c", code], input=json.dumps(manifest), text=True, capture_output=True)
(EVIDENCE / "image-source-check.json").write_text(result.stdout)
print(result.stdout.strip())
result.check_returncode()
