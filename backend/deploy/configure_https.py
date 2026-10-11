"""Generate only the Nginx HTTPS boundary; never interpolate unchecked env text."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oj.https import https_config  # noqa: E402


def configure(directory, environ):
    config = https_config(environ)
    mode = config["mode"]
    protocol = []
    if mode == "proxy":
        protocol += ["set_real_ip_from " + value + ";" for value in config["proxies"]]
        protocol += ["real_ip_header X-Forwarded-For;", "real_ip_recursive on;"]
        protocol += ["geo $realip_remote_addr $oj_trusted_proxy {", "    default 0;"]
        protocol += ["    " + value + " 1;" for value in config["proxies"]]
        protocol += ["}", 'map "$oj_trusted_proxy:$http_x_forwarded_proto" $oj_scheme {',
                     "    default $scheme;", "    ~^1:https$ https;", "}"]
    else:
        protocol += ["map $scheme $oj_scheme { default $scheme; }"]
    protocol += ['map "$oj_scheme:$uri" $oj_https_redirect {', "    default 0;",
                 "    ~^http:/api/judge_server_heartbeat/?$ 0;", "    ~^http: 1;", "}"]
    protocol += ["map $oj_scheme $oj_hsts {", '    default "";']
    if config["hsts_seconds"]:
        protocol += ['    https "max-age=' + str(config["hsts_seconds"]) + '";']
    protocol += ["}"]
    directory = Path(directory)
    (directory / "https_protocol.conf").write_text("\n".join(protocol) + "\n")
    # In proxy mode, trust only the CIDRs above. Header spoofing otherwise
    # follows the actual HTTP scheme and receives the same HTTPS redirect.
    guard = "if ($oj_https_redirect) { return 308 https://$host$request_uri; }\n" if mode == "proxy" else ""
    (directory / "https_proxy_guard.conf").write_text(guard)
    target = "https_redirect.conf" if mode == "direct" else "locations.conf"
    for name, source in (("http_locations.conf", target), ("https_locations.conf", "locations.conf")):
        path = directory / name
        path.unlink(missing_ok=True)
        path.symlink_to(source)
    return config


if __name__ == "__main__":
    try:
        configure(Path(__file__).parent / "nginx", os.environ)
    except ValueError as error:
        raise SystemExit(str(error)) from None
