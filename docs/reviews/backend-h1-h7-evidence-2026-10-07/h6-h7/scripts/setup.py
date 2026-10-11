"""Disposable local acceptance environment; never reads existing app credentials."""
import json
import os
from pathlib import Path
import secrets
import subprocess

HERE = Path(__file__).resolve().parent
PREFIX = "xmuoj-h7-20261007"
PG = "xmuoj-ai-test-postgres-20261007"
IMAGE = "xmuoj-ai:h1-h7-20261007"


def run(*args, **kwargs):
    result = subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)
    return result.stdout.strip()


def exists(kind, name):
    return subprocess.run(["docker", kind, "inspect", name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


if not exists("network", PREFIX):
    run("docker", "network", "create", PREFIX)
networks = json.loads(run("docker", "inspect", PG))[0]["NetworkSettings"]["Networks"]
if PREFIX not in networks:
    run("docker", "network", "connect", "--alias", "h7-postgres", PREFIX, PG)
databases = run("docker", "exec", PG, "psql", "-U", "onlinejudge", "-Atc", "SELECT datname FROM pg_database")
if "xmuoj_h7" not in databases.splitlines():
    run("docker", "exec", PG, "createdb", "-U", "onlinejudge", "xmuoj_h7")
for suffix in ("data", "testcases", "judge-run", "judge-log"):
    if not exists("volume", PREFIX + "-" + suffix):
        run("docker", "volume", "create", PREFIX + "-" + suffix)

env_path = HERE / "runtime.env"
if not env_path.exists():
    token = secrets.token_urlsafe(32)
    env = {"POSTGRES_HOST": "h7-postgres", "POSTGRES_DB": "xmuoj_h7", "POSTGRES_USER": "onlinejudge",
           "POSTGRES_PASSWORD": "onlinejudge", "REDIS_HOST": "h7-redis", "OJ_HTTPS_MODE": "direct",
           "JUDGE_SERVER_TOKEN": token, "DJANGO_SUPERUSER_USERNAME": "h7root",
           "DJANGO_SUPERUSER_PASSWORD": secrets.token_urlsafe(24), "MAX_WORKER_NUM": "1",
           "GUNICORN_CMD_ARGS": "--timeout 180"}
    env_path.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    os.chmod(env_path, 0o600)
    judge_env = HERE / "judge.env"
    judge_env.write_text(f"TOKEN={token}\nSERVICE_URL=http://h7-judge:8080\nBACKEND_URL=http://h7-backend:8000/api/judge_server_heartbeat/\n")
    os.chmod(judge_env, 0o600)

if not exists("container", PREFIX + "-redis"):
    run("docker", "run", "-d", "--name", PREFIX + "-redis", "--network", PREFIX,
        "--network-alias", "h7-redis", "redis:7-alpine")

# Certificate is a local acceptance fixture, never a production certificate.
crt, key = HERE / "server.crt", HERE / "server.key"
if not crt.exists():
    config = HERE / "cert.cnf"
    config.write_text("[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n[dn]\nCN=localhost\n[v3]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\n")
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-config", str(config),
        "-keyout", str(key), "-out", str(crt))
    os.chmod(key, 0o600)
if os.environ.get("H7_PREPARE_ONLY") == "1":
    print("Prepared isolated H7 database, network, Redis, certificate and private configuration; application not started.")
    raise SystemExit(0)
if not exists("container", PREFIX + "-backend"):
    run("docker", "create", "--name", PREFIX + "-backend", "--network", PREFIX, "--network-alias", "h7-backend",
        "--env-file", str(env_path), "-p", "127.0.0.1:18080:8000", "-p", "127.0.0.1:18443:1443",
        "-v", PREFIX + "-data:/data", "-v", PREFIX + "-testcases:/data/test_case", IMAGE)
    run("docker", "run", "--rm", "--entrypoint", "sh", "-v", PREFIX + "-data:/data",
        "-v", str(HERE) + ":/fixtures:ro", IMAGE, "-c",
        "mkdir -p /data/ssl && cp /fixtures/server.crt /data/ssl/server.crt && cp /fixtures/server.key /data/ssl/server.key && chmod 600 /data/ssl/server.key")
    run("docker", "start", PREFIX + "-backend")
if not exists("container", PREFIX + "-judge"):
    run("docker", "run", "-d", "--name", PREFIX + "-judge", "--network", PREFIX, "--network-alias", "h7-judge",
        "--env-file", str(HERE / "judge.env"), "-v", PREFIX + "-testcases:/test_case:ro",
        "-v", PREFIX + "-judge-run:/judger", "-v", PREFIX + "-judge-log:/log",
        "registry.cn-hongkong.aliyuncs.com/oj-image/judge:1.6.1")
print(json.dumps({"network": PREFIX, "database": "xmuoj_h7", "https": "https://localhost:18443",
                  "containers": [PREFIX + "-" + name for name in ("backend", "redis", "judge")]}))
