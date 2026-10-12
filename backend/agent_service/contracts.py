"""Explicit service-specific allowlists. Parameter order follows the tool contract."""
import json
from pathlib import Path
from jsonschema import Draft7Validator, FormatChecker
from utils.contract_api import ContractError

API_SCHEMAS = json.loads(Path(__file__).with_name("api_schemas.json").read_text())
RESULT_SCHEMAS = dict(zip(("submission_feedback", "code_explanation", "socratic_hint", "learning_path_explanation"),
                          ("SubmissionFeedbackResult", "CodeExplanationResult", "SocraticHintResult", "LearningPathExplanationResult")))
SIGNATURES = {
    "get_student_profile": ("user_id",), "get_weak_points": ("user_id",), "get_learning_path": ("user_id",),
    "get_problem_info": ("problem_id",), "get_knowledge_dependencies": ("knowledge_id",),
    "get_problem_summary": ("problem_id",), "get_error_patterns": ("problem_id", "code_snippet", "verdict"),
    "get_algorithm_template": ("problem_id",), "get_knowledge_context": ("problem_id",),
    "get_student_recent_submissions": ("user_id", "problem_id"), "get_problem_knowledge": ("problem_id",),
    "get_hint_level": ("user_id", "problem_id"), "save_agent_conversation": ("user_id", "problem_id", "message"),
    "get_submission": ("submission_id",), "search_error_patterns": ("code_snippet", "verdict", "problem_id"),
    "get_student_problem_history": ("user_id", "problem_id"), "search_rag": ("query", "problem_id", "knowledge_id"),
}
ALLOWLIST = {
    "learning_path_explanation": ("get_student_profile", "get_weak_points", "get_learning_path", "get_problem_info", "get_knowledge_dependencies", "search_rag"),
    "submission_feedback": ("get_problem_summary", "get_error_patterns", "get_algorithm_template", "get_knowledge_context", "get_student_recent_submissions", "search_rag"),
    "socratic_hint": ("get_problem_info", "get_problem_knowledge", "get_student_profile", "search_rag", "get_hint_level", "save_agent_conversation"),
    "code_explanation": ("get_submission", "get_problem_info", "get_problem_knowledge", "get_algorithm_template",
                         "search_error_patterns", "get_student_problem_history", "search_rag"),
}
PARAMETERS = {
    "user_id": {"type": "integer", "minimum": 1}, "knowledge_id": {"type": "integer", "minimum": 1},
    "problem_id": {"type": "string", "minLength": 1, "maxLength": 100},
    "submission_id": {"type": "string", "minLength": 1, "maxLength": 64},
    "query": {"type": "string", "minLength": 1, "maxLength": 500},
    "message": {"type": "string", "minLength": 1, "maxLength": 16000},
    "code_snippet": {"type": "string", "minLength": 1, "maxLength": 100000},
    "verdict": {"type": "string", "enum": ["WA", "TLE", "MLE", "RE", "CE"]},
}


def api_schema(name):
    return {"$ref": "#/definitions/" + name, "definitions": API_SCHEMAS}


def validate_api(name, value, output=False):
    errors = list(Draft7Validator(api_schema(name), format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise ContractError("AGENT_OUTPUT_SCHEMA_INVALID" if output else "AGENT_INPUT_INVALID",
                            "模型返回格式不符合契约" if output else "请求格式或字段不合法", 422 if output else 400, retryable=output)


def tool_schema(service, name):
    if name not in ALLOWLIST.get(service, ()):
        raise ContractError("AGENT_TOOL_NOT_ALLOWED", "当前服务不能调用此工具", 403)
    args = ("query", "knowledge_id") if name == "search_rag" and service == "learning_path_explanation" else SIGNATURES[name]
    return {"type": "object", "additionalProperties": False, "required": list(args),
            "properties": {arg: PARAMETERS[arg] for arg in args}}


def model_tools(service):
    return [{"type": "function", "function": {"name": name, "description": "受控教学工具 " + name,
                                              "parameters": tool_schema(service, name)}} for name in ALLOWLIST[service]]


def result_schema(service):
    """Only the relevant output schema enters the model context."""
    def expand(value):
        if isinstance(value, list):
            return [expand(x) for x in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return expand(API_SCHEMAS[value["$ref"].rsplit("/", 1)[-1]])
        return {key: expand(item) for key, item in value.items()}
    return expand(API_SCHEMAS[RESULT_SCHEMAS[service]])
