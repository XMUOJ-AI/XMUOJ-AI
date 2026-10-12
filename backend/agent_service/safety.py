import ipaddress
import re
from urllib.parse import urlsplit
from rag.adapters import config
from rag.safety import normalize_text, normalized_texts, unsafe_content
from utils.contract_api import ContractError


def contains_internal_address(text):
    for url in re.findall(r"(?i)\bhttps?://[^\s\"<>\\，。；：！？]+", text):
        try:
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if host and ("." not in host or host.endswith((".localhost", ".local", ".internal", ".svc", ".cluster.local"))):
                return True
        else:
            if address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
                return True
    return False


def check_output(value):
    try:
        texts = list(normalized_texts(value))
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ContractError("AGENT_OUTPUT_BLOCKED", "输出内容无法安全展示，已阻断", 422) from None
    forbidden = (r"(?is)(```\s*(?:python|c\+\+|cpp|c|java|javascript)"
                 r"|/(?:Users|home|var|etc|tmp|root|opt|srv|run|proc|sys|data|app|usr|mnt|media|workspace|test_case|judger)/"
                 r"|\b[A-Z]:[\\/]|\\\\[A-Z0-9._-]+\\"
                 r"|(?:system prompt|系统提示词)\s*[:：]|(?:已经|已)(?:读取|获取)隐藏测试|(?:我会|已经|已)(?:替你|为你)(?:提交|修改)代码)")
    secrets = [normalize_text(config(name, "")) for name in ("AGENT_MODEL_API_KEY", "RAG_EMBEDDING_API_KEY", "RAG_MILVUS_TOKEN")]
    if unsafe_content(value) or any(
            re.search(forbidden, text) or contains_internal_address(text)
            or any(secret and len(secret) >= 8 and secret in text for secret in secrets) for text in texts):
        raise ContractError("AGENT_OUTPUT_BLOCKED", "输出包含不适合展示的内容，已阻断", 422)
