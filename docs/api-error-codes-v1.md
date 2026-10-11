# XMUOJ-AI 第一期统一错误码

- 版本：1.0.0
- 状态：已批准／冻结
- 更新日期：2026-08-10
- 适用范围：Agent Run API、Agent 内部工具、学习与推荐工作流 API、题目批量导入 API 与 Management Command

## 1. 响应规则

新接口使用既有 XMUOJ `error/data` 包络，同时返回正确的 HTTP 状态码。

```json
{
  "error": "AGENT_SUBMISSION_NOT_FINAL",
  "data": {
    "message": "提交仍在判题中",
    "retryable": true,
    "details": {
      "submission_id": "abc123",
      "status": "JUDGING"
    }
  },
  "request_id": "req_01J..."
}
```

规则：

- `error` 是稳定机器代码，前端不得依赖 `message` 判断逻辑。
- `message` 为面向用户的简体中文安全提示。
- `retryable` 表示在外部状态变化后重试是否可能成功。
- `details` 只放非敏感结构化信息。
- `request_id` 必须进入服务端日志，供排障使用。
- 未预期异常统一转换为 `*_INTERNAL_ERROR`，不得返回堆栈。

## 2. HTTP 状态映射

| HTTP | 使用场景 |
|---:|---|
| 400 | 请求格式、字段或枚举错误 |
| 401 | 未认证或认证失效 |
| 403 | 已认证但无对象或功能权限 |
| 404 | 对当前用户可见范围内不存在 |
| 409 | 状态、幂等键、批次或重复数据冲突 |
| 413 | 请求、代码或数据包过大 |
| 422 | Schema、业务校验或内容校验失败 |
| 429 | 速率、并发或预算限制 |
| 500 | 未预期内部错误 |
| 503 | 模型、RAG、Judge 或其他依赖不可用 |
| 504 | 工具或模型调用超时 |

## 3. Agent 公共错误码

| 错误码 | HTTP | 可重试 | 含义 |
|---|---:|:---:|---|
| `AGENT_AUTH_REQUIRED` | 401 | 否 | 未登录或 Session/Bearer Token 已失效 |
| `AGENT_PERMISSION_DENIED` | 403 | 否 | 当前用户无此 Agent 功能权限 |
| `AGENT_FEATURE_DISABLED` | 403 | 否 | 功能、题目类型或用户组未开启，例如一期比赛题 |
| `AGENT_INPUT_INVALID` | 400 | 否 | 请求字段、类型或枚举不合法 |
| `AGENT_INPUT_TOO_LARGE` | 413 | 否 | 代码、题面、学生输入或上下文超限 |
| `AGENT_IDEMPOTENCY_CONFLICT` | 409 | 否 | 同一幂等键对应了不同请求 |
| `AGENT_RATE_LIMITED` | 429 | 是 | 用户调用频率或并发超限 |
| `AGENT_BUDGET_EXCEEDED` | 429 | 是 | 工具次数、token 或单日预算超限 |
| `AGENT_DEPENDENCY_NOT_READY` | 503 | 是 | Elo、路径、RAG 等模块尚未准备好 |
| `AGENT_PROVIDER_UNAVAILABLE` | 503 | 是 | 模型供应商不可用 |
| `AGENT_PROVIDER_TIMEOUT` | 504 | 是 | 模型调用超时 |
| `AGENT_OUTPUT_SCHEMA_INVALID` | 422 | 是 | 模型输出无法通过结构校验 |
| `AGENT_OUTPUT_BLOCKED` | 422 | 是 | 输出包含完整答案、敏感信息或违反安全边界 |
| `AGENT_INTERNAL_ERROR` | 500 | 是 | 未预期内部错误 |

## 4. Agent 对象错误码

| 错误码 | HTTP | 可重试 | 含义 |
|---|---:|:---:|---|
| `AGENT_RUN_NOT_FOUND` | 404 | 否 | Run 不存在或不属于当前用户 |
| `AGENT_RUN_NOT_FINISHED` | 409 | 是 | Run 尚未完成，不能评价或读取最终结果 |
| `AGENT_RUN_ALREADY_FINISHED` | 409 | 否 | 对已终态 Run 执行了不允许的状态操作 |
| `AGENT_PROBLEM_NOT_FOUND` | 404 | 否 | 题目不存在或当前用户不可见 |
| `AGENT_PROBLEM_FORBIDDEN` | 403 | 否 | 无权读取题目，例如未加入的比赛或考试题 |
| `AGENT_SUBMISSION_NOT_FOUND` | 404 | 否 | 提交不存在 |
| `AGENT_SUBMISSION_FORBIDDEN` | 403 | 否 | 提交不属于当前用户且无管理权限 |
| `AGENT_SUBMISSION_NOT_FINAL` | 409 | 是 | 提交为 PENDING/JUDGING，不能分析 |
| `AGENT_CONVERSATION_NOT_FOUND` | 404 | 否 | 会话不存在或不属于当前用户 |
| `AGENT_HINT_NOT_AVAILABLE` | 409 | 是 | 思考倒计时未结束或尚未提交题意理解 |
| `AGENT_HINT_LEVEL_CONFLICT` | 409 | 是 | 提示层级被其他请求更新，需刷新后重试 |
| `AGENT_FEEDBACK_INVALID` | 400 | 否 | 反馈枚举或评论不合法 |

对于 `AGENT_RUN_NOT_FOUND`，接口不得通过不同消息泄露“Run 存在但属于其他用户”。

## 5. Agent 工具错误码

| 错误码 | HTTP/内部状态 | 可重试 | 含义 |
|---|---:|:---:|---|
| `AGENT_TOOL_NOT_ALLOWED` | 403 | 否 | 当前 service_type 不允许调用该工具 |
| `AGENT_TOOL_ARGUMENT_INVALID` | 400 | 否 | 工具参数不符合契约 |
| `AGENT_TOOL_PERMISSION_DENIED` | 403 | 否 | 工具对象级权限检查失败 |
| `AGENT_TOOL_RESULT_TOO_LARGE` | 413 | 否 | 工具结果超过最大上下文 |
| `AGENT_TOOL_TIMEOUT` | 504 | 是 | 工具调用超时 |
| `AGENT_TOOL_DEPENDENCY_UNAVAILABLE` | 503 | 是 | 工具依赖不可用 |
| `AGENT_TOOL_INTERNAL_ERROR` | 500 | 是 | 工具未预期错误 |
| `AGENT_RAG_NO_RESULT` | 200/内部成功 | 否 | RAG 无命中；这是空结果，不是公共 API 失败 |

## 6. 学习与推荐工作流错误码

| 错误码 | HTTP | 可重试 | 含义 |
|---|---:|:---:|---|
| `LEARNING_AUTH_REQUIRED` | 401 | 否 | 未登录或 Session 已失效 |
| `LEARNING_PERMISSION_DENIED` | 403 | 否 | 无教师权限，或无权查看目标学生/班级 |
| `LEARNING_INPUT_INVALID` | 400 | 否 | limit、class_id 或目标知识点参数不合法 |
| `LEARNING_PATH_NOT_FOUND` | 404 | 是 | 当前学生尚无活动学习路径 |
| `LEARNING_STUDENT_NOT_FOUND` | 404 | 否 | 学生不存在或不在教师可管理范围内 |
| `LEARNING_CLASS_NOT_FOUND` | 404 | 否 | 班级不存在或不在教师可管理范围内 |
| `LEARNING_REFRESH_CONFLICT` | 409 | 是 | 路径正在刷新，或幂等键对应不同请求 |
| `LEARNING_RATE_LIMITED` | 429 | 是 | 手动刷新频率超限 |
| `LEARNING_DEPENDENCY_NOT_READY` | 503 | 是 | Elo、知识图谱或推荐工作流尚未准备好 |
| `LEARNING_INTERNAL_ERROR` | 500 | 是 | 学习工作流未预期错误 |

学生尚无掌握度记录时，`GET /api/learning/profile` 返回 HTTP 200 和空 `knowledge_states`；没有薄弱点时，`GET /api/learning/weakness` 返回 HTTP 200 和空 `weak_points`，均不视为错误。

教师端 404 不得通过不同消息泄露“学生或班级存在但教师无权查看”。

## 7. 题目导入批次错误码

| 错误码 | HTTP | 可重试 | 级别 | 含义 |
|---|---:|:---:|---|---|
| `IMPORT_ARCHIVE_REQUIRED` | 400 | 否 | fatal | 未上传 ZIP |
| `IMPORT_ARCHIVE_TOO_LARGE` | 413 | 否 | fatal | ZIP 超过限制 |
| `IMPORT_ARCHIVE_INVALID` | 422 | 否 | fatal | 不是合法 ZIP 或目录结构损坏 |
| `IMPORT_ARCHIVE_UNSAFE_PATH` | 422 | 否 | fatal | 包含绝对路径、`..` 或符号链接 |
| `IMPORT_ARCHIVE_SUSPICIOUS_COMPRESSION` | 422 | 否 | fatal | 疑似 Zip Bomb |
| `IMPORT_BATCH_CONFLICT` | 409 | 否 | fatal | 相同 batch_id 对应不同文件 |
| `IMPORT_BATCH_DUPLICATE` | 200 | 否 | info | 完全相同 ZIP 已处理，返回已有批次 |
| `IMPORT_BATCH_NOT_FOUND` | 404 | 否 | fatal | 批次不存在 |
| `IMPORT_BATCH_STATE_CONFLICT` | 409 | 是 | fatal | 当前批次状态不允许该操作 |
| `IMPORT_SCHEMA_VERSION_UNSUPPORTED` | 422 | 否 | fatal | schema_version 不受支持 |
| `IMPORT_MANIFEST_MISSING` | 422 | 否 | fatal | 缺少 manifest.json |
| `IMPORT_MANIFEST_INVALID` | 422 | 否 | fatal | manifest 字段或 JSON 不合法 |
| `IMPORT_FILE_MISSING` | 422 | 否 | fatal/error | manifest 声明的文件不存在 |
| `IMPORT_FILE_SIZE_MISMATCH` | 422 | 否 | fatal/error | 文件大小不一致 |
| `IMPORT_FILE_HASH_MISMATCH` | 422 | 否 | fatal/error | 文件 SHA-256 不一致 |
| `IMPORT_FILE_TYPE_FORBIDDEN` | 422 | 否 | fatal/error | 存在禁止文件类型 |
| `IMPORT_PROBLEM_COUNT_MISMATCH` | 422 | 否 | fatal | JSONL 行数与 manifest 不一致 |
| `IMPORT_JSONL_INVALID` | 422 | 否 | error | 指定行不是合法 JSON |
| `IMPORT_PROBLEM_SCHEMA_INVALID` | 422 | 否 | error | 单题不符合 JSON Schema |
| `IMPORT_CONTENT_HASH_MISMATCH` | 422 | 否 | error | 规范内容哈希不一致 |
| `IMPORT_DISPLAY_ID_CONFLICT` | 409 | 否 | error | 生成的 Problem._id 已被其他来源身份占用 |
| `IMPORT_SOURCE_DUPLICATE` | 409 | 否 | warning | 来源平台和题号已存在 |
| `IMPORT_CONTENT_DUPLICATE` | 409 | 否 | warning | 内容哈希与已有题目相同 |
| `IMPORT_SOURCE_UPDATED` | 409 | 否 | warning | 来源键相同但内容发生变化 |

## 8. 题目字段和资源错误码

| 错误码 | HTTP | 级别 | 含义 |
|---|---:|---|---|
| `IMPORT_HTML_UNSAFE` | 422 | error | 题面包含危险 HTML 或 URL |
| `IMPORT_ASSET_MISSING` | 422 | error | 题面引用资源不存在 |
| `IMPORT_ASSET_HASH_MISMATCH` | 422 | error | 资源哈希不一致 |
| `IMPORT_ASSET_TYPE_FORBIDDEN` | 422 | error | 资源类型不允许 |
| `IMPORT_LANGUAGE_UNKNOWN` | 422 | error | allowed_languages 包含后端未知语言 |
| `IMPORT_TAG_UNKNOWN` | 422 | warning/error | 统一标签不存在，级别由策略决定 |
| `IMPORT_TAG_MAPPING_CONFLICT` | 409 | warning | 新映射与后端已有映射冲突 |
| `IMPORT_KNOWLEDGE_CODE_UNKNOWN` | 422 | warning/error | knowledge_code 不存在 |
| `IMPORT_PRIMARY_KNOWLEDGE_MISSING` | 422 | warning | 没有 primary 知识点候选 |
| `IMPORT_TESTCASE_MANIFEST_MISSING` | 422 | error | ready 题目缺测试 manifest |
| `IMPORT_TESTCASE_INVALID` | 422 | error | 测试点字段、路径或分数不合法 |
| `IMPORT_TESTCASE_HASH_MISMATCH` | 422 | error | 测试输入/输出哈希不一致 |
| `IMPORT_TESTCASE_OUTPUT_MISSING` | 422 | error | 非 SPJ 测试点缺输出 |
| `IMPORT_TESTCASE_SCORE_INVALID` | 422 | error | OI 分数非法或总分不一致 |
| `IMPORT_STATEMENT_ONLY` | 200 | info | 只有题面，只进入采集库，不发布 |
| `IMPORT_PROVENANCE_INCOMPLETE` | 422 | error | 来源许可或采集信息不完整 |
| `IMPORT_COMPLIANCE_REVIEW_REQUIRED` | 422 | warning | 必须人工确认合规后才能提交 |

## 9. 导入执行错误码

| 错误码 | HTTP | 可重试 | 含义 |
|---|---:|:---:|---|
| `IMPORT_COMMIT_HAS_ERRORS` | 409 | 否 | 批次仍有错误且未启用 allow_partial |
| `IMPORT_WARNING_NOT_ACKNOWLEDGED` | 409 | 否 | 存在未确认警告 |
| `IMPORT_PROBLEM_CREATE_FAILED` | 500 | 是 | 创建 Problem 失败且已回滚 |
| `IMPORT_TESTCASE_SAVE_FAILED` | 500 | 是 | 保存测试数据失败且已回滚 |
| `IMPORT_ASSET_SAVE_FAILED` | 500 | 是 | 保存资源失败且已回滚 |
| `IMPORT_PARTIAL_SUCCESS` | 200 | 否 | 允许部分导入时，部分题目失败 |
| `IMPORT_INTERNAL_ERROR` | 500 | 是 | 未预期导入错误 |

## 10. Management Command 退出码

| 退出码 | 含义 |
|---:|---|
| 0 | dry-run 无 error，或 commit 全部成功 |
| 1 | 有数据错误、未确认警告或部分导入失败 |
| 2 | 参数、文件、安全、权限或运行环境错误 |

命令的 JSON 报告使用与 API 完全相同的错误码。

## 11. 前端处理建议

- 401：跳转登录或刷新认证。
- 403：展示权限/功能未开放提示，不自动重试。
- `AGENT_SUBMISSION_NOT_FINAL`：按 1、2、4、8 秒退避轮询，最长 30 秒。
- 429：读取服务端 `Retry-After`，按钮进入倒计时。
- 503/504：允许用户手动重试；不得无限自动重试。
- `AGENT_OUTPUT_BLOCKED`：展示安全降级提示，不显示原始模型输出。
- `LEARNING_PATH_NOT_FOUND`：引导用户调用一次手动刷新，不自动循环刷新。
- `LEARNING_RATE_LIMITED`：读取服务端 `Retry-After`，禁用刷新按钮直至倒计时结束。
- 导入 warning：必须在管理员确认界面列出，不能静默忽略。

## 12. 兼容性

- 错误码一经发布不得改变含义。
- 新增错误码为向后兼容修改。
- 废弃错误码至少保留一个主版本，并在响应 `details.deprecated=true`。
- 未识别错误码时，前端按所属 HTTP 状态使用通用提示处理。
