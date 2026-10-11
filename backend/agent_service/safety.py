import json
import re
from rag.adapters import config
from rag.services import unsafe_content
from utils.contract_api import ContractError


def check_output(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
    forbidden = (r"(?is)(```\s*(?:python|c\+\+|cpp|c|java|javascript)"
                 r"|(?:/Users/|/home/|/var/|https?://(?:localhost|127\.|10\.|192\.168\.))"
                 r"|(?:system prompt|系统提示词)\s*[:：]|(?:已经|已)(?:读取|获取)隐藏测试|(?:我会|已经|已)(?:替你|为你)(?:提交|修改)代码)")
    secrets = [config(name, "") for name in ("AGENT_MODEL_API_KEY", "RAG_EMBEDDING_API_KEY", "RAG_MILVUS_TOKEN")]
    if unsafe_content(text) or re.search(forbidden, text) or any(secret and len(secret) >= 8 and secret in text for secret in secrets):
        raise ContractError("AGENT_OUTPUT_BLOCKED", "输出包含不适合展示的内容，已阻断", 422)
