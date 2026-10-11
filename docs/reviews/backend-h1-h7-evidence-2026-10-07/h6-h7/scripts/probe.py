"""Real HTTPS/API/queue/JudgeServer checks. Never prints or saves password values."""
import io
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import xml.etree.ElementTree as ET
import zipfile

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EVIDENCE = ROOT / "docs/reviews/backend-h1-h7-evidence-2026-10-07/h6-h7"
BASE = "https://localhost:18443"
CONTAINER = "xmuoj-h7-20261007-backend"
env = dict(line.split("=", 1) for line in (HERE / "runtime.env").read_text().splitlines())
checks = {}


def record(name, condition, detail=None):
    checks[name] = {"passed": bool(condition), "detail": detail}
    (EVIDENCE / "runtime-results.json").write_text(json.dumps(checks, indent=2, ensure_ascii=False))
    print(name, "PASS" if condition else "FAIL", flush=True)
    assert condition, name


def session():
    client = requests.Session()
    client.trust_env = False
    client.verify = str(HERE / "server.crt")
    return client


def get(client, path, **kwargs):
    return client.get(BASE + path, timeout=45, **kwargs)


def post(client, path, data, csrf=True, **kwargs):
    headers = {"Referer": BASE + "/"}
    if csrf:
        headers["X-CSRFToken"] = client.cookies.get("csrftoken", "")
    headers.update(kwargs.pop("headers", {}))
    return client.post(BASE + path, json=data, headers=headers, timeout=90, **kwargs)


def payload(response):
    assert response.headers.get("Content-Type", "").startswith("application/json"), (response.status_code, response.request.path_url)
    data = response.json()
    assert response.status_code < 300 and data.get("error") is None, (response.status_code, data)
    return data["data"]


def shell(code):
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "python", "manage.py", "shell"],
        input=code, text=True, capture_output=True, check=True)
    return result.stdout.strip()


admin = session()
http = requests.Session()
http.trust_env = False
redirect = http.get("http://localhost:18080/api/website", headers={"X-Forwarded-Proto": "https"}, allow_redirects=False, timeout=20)
record("direct_http_spoof_redirect", redirect.status_code == 308 and redirect.headers.get("Location", "").startswith("https://"))
website = get(admin, "/api/website")
record("https_hsts", website.status_code == 200 and website.headers.get("Strict-Transport-Security") == "max-age=3600")
root = get(admin, "/")
admin_html = get(admin, "/admin/")
record("frontend_html", root.status_code == 200 and admin_html.status_code == 200 and "<html" in root.text.lower() and "<html" in admin_html.text.lower())
class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("src"):
            self.sources.append(dict(attrs)["src"])

parser = Scripts()
parser.feed(root.text)
scripts = parser.sources
assets = []
for url in scripts:
    if url.startswith("/"):
        response = get(admin, url)
        assets.append({"url": url, "status": response.status_code, "hsts": response.headers.get("Strict-Transport-Security")})
record("frontend_scripts", bool(assets) and all(x["status"] == 200 and x["hsts"] == "max-age=3600" for x in assets), assets)
get(admin, "/api/profile")
payload(post(admin, "/api/login", {"username": env["DJANGO_SUPERUSER_USERNAME"], "password": env["DJANGO_SUPERUSER_PASSWORD"]}))
record("secure_cookies", all(admin.cookies.get(name) and next(c for c in admin.cookies if c.name == name).secure for name in ("csrftoken", "sessionid")))
username = "h7student_" + uuid4().hex[:10]
rows = {"users": [[username, "真实联调学生", "H7验收班"]]}
denied = post(admin, "/api/admin/user", rows, csrf=False)
record("csrf_rejection", denied.status_code == 403)
created = payload(post(admin, "/api/admin/user", rows))
again = payload(post(admin, "/api/admin/user", rows))
record("import_retry_same_export", created["created_count"] == 1 and again["file_id"] == created["file_id"])
download = get(admin, "/api/admin/generate_user", params={"file_id": created["file_id"]})
download_again = get(admin, "/api/admin/generate_user", params={"file_id": created["file_id"]})
record("private_retryable_export", download.status_code == 200 and download.content == download_again.content and "no-store" in download.headers.get("Cache-Control", ""))
ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
    strings = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
    sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    values = [strings[int(cell.find("x:v", ns).text)] for cell in sheet.findall(".//x:row", ns)[1].findall("x:c", ns)]
student = session()
get(student, "/api/profile")
payload(post(student, "/api/login", {"username": values[0], "password": values[1]}))
record("random_password_login", values[0] == username and len(values[1]) >= 20 and values[1] != "123456")
del values, strings
unauthorized = get(student, "/api/admin/generate_user", params={"file_id": created["file_id"]})
record("student_cannot_export", unauthorized.status_code == 403 or unauthorized.json().get("error") is not None)
seed = shell((EVIDENCE / "seed_judge.py").read_text())
problem = json.loads(seed.splitlines()[-1])
submission = payload(post(student, "/api/submission", {"problem_id": problem["problem_id"], "language": "Python3", "code": "a,b=map(int,input().split());print(a+b)"}))
sid = submission["submission_id"]
start = time.monotonic()
result = None
while time.monotonic() - start < 240:
    result = payload(get(student, "/api/submission", params={"id": sid}))
    if result["result"] not in (6, 7):
        break
    time.sleep(2)
record("real_judgeserver_accepted", result["result"] == 0, {"submission_id": sid, "result": result["result"], "elapsed_seconds": round(time.monotonic() - start, 3)})
while time.monotonic() - start < 300:
    profile = payload(get(student, "/api/learning/profile"))
    states = profile["knowledge_states"]
    if states and states[0]["attempt_count"] == 1:
        break
    time.sleep(2)
record("real_queue_profile", bool(states) and states[0]["attempt_count"] == 1 and states[0]["accepted_count"] == 1, profile)
payload(post(admin, "/api/admin/submission/rejudge", {"id": sid}))
time.sleep(3)
for _ in range(100):
    replay = payload(get(student, "/api/submission", params={"id": sid}))
    if replay["result"] not in (6, 7) and not replay.get("statistic_info", {}).get("_rejudge_pending"):
        break
    time.sleep(2)
time.sleep(3)
reprofile = payload(get(student, "/api/learning/profile"))
record("real_rejudge_idempotent", replay["result"] == 0 and reprofile["knowledge_states"][0]["attempt_count"] == 1)
judge_container = "xmuoj-h7-20261007-judge"
try:
    subprocess.run(["docker", "stop", "--time", "5", judge_container], check=True, capture_output=True)
    time.sleep(7)  # Judge heartbeat expires after six seconds.
    queued = payload(post(student, "/api/submission", {"problem_id": problem["problem_id"], "language": "Python3", "code": "print(sum(map(int,input().split())))"}))
    time.sleep(3)
    pending = payload(get(student, "/api/submission", params={"id": queued["submission_id"]}))
    record("real_judge_offline_queued", pending["result"] == 6)
finally:
    subprocess.run(["docker", "start", judge_container], check=True, capture_output=True)
for _ in range(120):
    recovered = payload(get(student, "/api/submission", params={"id": queued["submission_id"]}))
    if recovered["result"] not in (6, 7):
        break
    time.sleep(2)
record("real_judge_restart_recovers_queue", recovered["result"] == 0, {"submission_id": queued["submission_id"], "result": recovered["result"]})
for _ in range(60):
    updated = payload(get(student, "/api/learning/profile"))["knowledge_states"]
    if updated and updated[0]["attempt_count"] == 2:
        break
    time.sleep(2)
record("recovered_judge_updates_profile", bool(updated) and updated[0]["attempt_count"] == 2 and updated[0]["accepted_count"] == 2)
path = payload(post(student, "/api/recommendation/refresh", {}))
record("real_path_generation", bool(path.get("path_id")), path)
missing = post(student, "/api/agent/v1/runs", {"service_type": "code_explanation", "submission_id": sid, "options": {"language": "zh-CN"}}, headers={"Idempotency-Key": str(uuid4())})
record("missing_model_explicit_503", missing.status_code == 503 and missing.json().get("error") == "AGENT_DEPENDENCY_NOT_READY", {"status": missing.status_code, "response": missing.json()})
metadata = shell("import json, os, stat\nfrom pathlib import Path\np=Path('/data/user_credentials')\nprint(json.dumps({'directory':oct(stat.S_IMODE(p.stat().st_mode)), 'owner':p.stat().st_uid, 'files':[{'mode':oct(stat.S_IMODE(x.stat().st_mode)), 'owner':x.stat().st_uid} for x in p.glob('*.xlsx')]}))")
metadata = json.loads(metadata.splitlines()[-1])
record("credential_disk_permissions", metadata["directory"] == "0o700" and metadata["owner"] == 900 and bool(metadata["files"]) and all(x == {"mode": "0o600", "owner": 900} for x in metadata["files"]), metadata)
shell("from account.models import UserCredentialExport\nfrom django.utils import timezone\nfrom datetime import timedelta\n"
      + "UserCredentialExport.objects.filter(pk=" + repr(created["file_id"]) + ").update(expires_at=timezone.now()-timedelta(seconds=1))")
cleanup_started = time.monotonic()
exists = True
while time.monotonic() - cleanup_started < 90:
    exists = subprocess.run(["docker", "exec", CONTAINER, "test", "-e", "/data/user_credentials/" + created["file_id"] + ".xlsx"],
                            capture_output=True).returncode == 0
    if not exists:
        break
    time.sleep(2)
record("background_credentials_cleanup", not exists, {"observed_seconds": round(time.monotonic() - cleanup_started, 3)})
(HERE / "probe-state.json").write_text(json.dumps({"username": username, "submission_id": sid, "export_id": created["file_id"]}))
os.chmod(HERE / "probe-state.json", 0o600)
print("All runtime checks passed; model/Embedding/Milvus real integration remains unverified.")
