"""Temporarily exercise Nginx proxy trust in the disposable H7 container."""
import json
from pathlib import Path
import subprocess
import time

import requests

CONTAINER = "xmuoj-h7-20261007-backend"
HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[1] / "docs/reviews/backend-h1-h7-evidence-2026-10-07/h6-h7"
checks = {}


def command(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout.strip()


def mode(value):
    command("docker", "exec", "-e", "OJ_HTTPS_MODE=" + value,
            "-e", "OJ_TRUSTED_PROXY_CIDRS=127.0.0.1/32", CONTAINER,
            "python", "/app/deploy/configure_https.py")
    command("docker", "exec", CONTAINER, "nginx", "-t", "-c", "/app/deploy/nginx/nginx.conf")
    command("docker", "exec", CONTAINER, "nginx", "-s", "reload", "-c", "/app/deploy/nginx/nginx.conf")
    time.sleep(1)


def record(name, passed, detail):
    checks[name] = {"passed": bool(passed), "detail": detail}
    print(name, "PASS" if passed else "FAIL", flush=True)
    assert passed, name


try:
    mode("proxy")
    client = requests.Session()
    client.trust_env = False
    untrusted = client.get("http://localhost:18080/api/website", headers={
        "X-Forwarded-Proto": "https", "X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
        allow_redirects=False, timeout=30)
    record("untrusted_cannot_forge_proxy", untrusted.status_code == 308, untrusted.status_code)
    for name, protocol, expected in (("https", "https", 200), ("uppercase", "HTTPS", 308),
                                     ("comma", "https,http", 308), ("http", "http", 308)):
        result = command("docker", "exec", CONTAINER, "curl", "--noproxy", "*", "-sS", "-D", "-",
                         "-o", "/dev/null", "-H", "X-Forwarded-Proto: " + protocol,
                         "-H", "X-Forwarded-For: 203.0.113.9", "http://127.0.0.1:8000/api/website?probe=" + name)
        status = int(result.splitlines()[0].split()[1])
        record("trusted_protocol_" + name, status == expected and (expected != 200 or "strict-transport-security: max-age=3600" in result.lower()), {"status": status, "headers": result})
    logs = command("docker", "exec", CONTAINER, "tail", "-n", "15", "/data/log/nginx_access.log")
    matching = [line for line in logs.splitlines() if "?probe=https " in line]
    record("trusted_client_ip_restored", bool(matching) and all(line.startswith("203.0.113.9 -") for line in matching), matching)
    heartbeat = client.post("http://localhost:18080/api/judge_server_heartbeat/", json={"hostname": "invalid-token-probe", "action": "heartbeat", "judger_version": "test", "cpu_core": 1, "memory": 0, "cpu": 0, "service_url": "http://invalid.example"}, allow_redirects=False, timeout=30)
    record("heartbeat_requires_token", heartbeat.status_code not in (301, 302, 307, 308) and heartbeat.json().get("data") == "Invalid token",
           {"status": heartbeat.status_code, "body": heartbeat.json()})
finally:
    mode("direct")
    (EVIDENCE / "proxy-results.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2))
print("Restored direct TLS mode. Actual production gateway remains unverified.")
