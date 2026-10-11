"""Real chat-completions-compatible HTTP adapter; tests replace it with an isolated fixture."""
import time
from rag.adapters import config, post_json
from utils.contract_api import ContractError


def complete(messages, tools, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ContractError("AGENT_PROVIDER_TIMEOUT", "模型运行超时", 504, retryable=True)
    try:
        response = post_json(config("AGENT_MODEL_URL"), {"model": config("AGENT_MODEL_NAME"), "messages": messages,
                                                         "tools": tools, "tool_choice": "auto", "response_format": {"type": "json_object"}, "max_tokens": 2000,
                                                         "temperature": 0.2}, token=config("AGENT_MODEL_API_KEY", ""), timeout=min(30, remaining))
    except ContractError:
        if time.monotonic() >= deadline:
            raise ContractError("AGENT_PROVIDER_TIMEOUT", "模型运行超时", 504, retryable=True)
        raise ContractError("AGENT_PROVIDER_UNAVAILABLE", "模型供应商暂时不可用", 503, retryable=True)

    try:
        choice = response["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict) or choice.get("finish_reason") == "length":
            raise ValueError()
        usage = response.get("usage", {})
        counts = {name: usage.get(name, 0) for name in ("prompt_tokens", "completion_tokens")}
        if any(type(x) is not int or x < 0 for x in counts.values()) or counts["completion_tokens"] > 2000:
            raise ValueError()
        return message, counts
    except (KeyError, IndexError, TypeError, ValueError):
        raise ContractError("AGENT_OUTPUT_SCHEMA_INVALID", "模型响应不符合协议", 422, retryable=True)
