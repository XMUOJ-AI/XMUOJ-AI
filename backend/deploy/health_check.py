import json
import socket
import sys
import urllib.request
import xmlrpc.client

PROBE_TIMEOUT = 3


def check_health():
    try:
        with xmlrpc.client.ServerProxy("http://127.0.0.1:9005/RPC2") as server:
            processes = server.supervisor.getAllProcessInfo()
        if not processes or any(process["state"] != 20 for process in processes):
            return "Supervisor process is not running"
    except Exception:
        return "Supervisor probe failed"

    # Ignore HTTP_PROXY/ALL_PROXY: the readiness probe must stay on loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:8080/api/website", timeout=PROBE_TIMEOUT) as response:
            if response.status != 200:
                return "Application returned an unexpected HTTP status"
            payload = json.loads(response.read(1024 * 1024))
        if not isinstance(payload, dict) or payload.get("error") is not None or not isinstance(payload.get("data"), dict):
            return "Application returned an invalid health response"
    except Exception:
        return "Application HTTP probe failed"
    return None


if __name__ == "__main__":
    # xmlrpc Transport uses this default; the HTTP probe also has an explicit bound.
    socket.setdefaulttimeout(PROBE_TIMEOUT)
    failure = check_health()
    if failure:
        print(failure, file=sys.stderr)
    sys.exit(1 if failure else 0)
