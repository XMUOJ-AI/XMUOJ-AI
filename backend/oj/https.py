"""Shared HTTPS configuration for Django and the container's Nginx boundary."""
import ipaddress


def https_config(environ):
    default = "direct" if environ.get("OJ_ENV") == "production" or environ.get("FORCE_HTTPS") else "off"
    mode = environ.get("OJ_HTTPS_MODE", default)
    if mode not in ("off", "direct", "proxy"):
        raise ValueError("OJ_HTTPS_MODE must be off, direct or proxy")
    proxies = []
    for value in environ.get("OJ_TRUSTED_PROXY_CIDRS", "").split(","):
        if value.strip():
            if "%" in value:
                raise ValueError("OJ_TRUSTED_PROXY_CIDRS cannot contain IPv6 scope identifiers")
            proxies.append(str(ipaddress.ip_network(value.strip(), strict=False)))
    if mode == "proxy" and not proxies:
        raise ValueError("proxy HTTPS mode requires OJ_TRUSTED_PROXY_CIDRS")
    if any(ipaddress.ip_network(value).prefixlen == 0 for value in proxies):
        raise ValueError("OJ_TRUSTED_PROXY_CIDRS cannot trust the entire Internet")
    try:
        seconds = int(environ.get("OJ_HSTS_SECONDS", "3600"))
    except ValueError:
        raise ValueError("OJ_HSTS_SECONDS must be an integer") from None
    if not 0 <= seconds <= 31536000:
        raise ValueError("OJ_HSTS_SECONDS must be between 0 and 31536000")
    return {"mode": mode, "proxies": proxies, "hsts_seconds": seconds if mode != "off" else 0}
