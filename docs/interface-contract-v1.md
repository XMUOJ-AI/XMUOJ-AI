> 2026-10-07 版本提示：本文保留第一期旧基线。知识点目标需求以 [新交付包 v0.9.9](knowledge/review-v0.9.9/README.md) 为准，但仍待模型批准和契约修正；本文相关内容不是当前已冻结实施规范。详见 [契约评审报告](reviews/contract-review-2026-10-07.md)。

# XMUOJ-AI 第一期接口契约

- 状态：已冻结
- 版本：1.0.0
- 更新日期：2026-08-10
- 交付任务：确定第一期接口契约

## 1. 文件定位

本文件是“确定接口契约”任务的唯一权威入口，汇总公共 REST API、Agent Runtime 内部工具、统一错误、版本和变更规则。为保持 Swagger、OpenAPI 校验器和代码生成器的标准兼容性，三个业务域仍保留为独立 OpenAPI 附件。

发生冲突时按下列优先级解释：

1. HTTP 路径、方法、参数、状态码和请求响应 Schema 以对应 OpenAPI 为准。
2. Agent 内部工具名称、参数顺序、权限、预算和禁止能力以 [agent-tool-contract-v1.md](./agent-tool-contract-v1.md) 为准。
3. 公共错误语义以 [api-error-codes-v1.md](./api-error-codes-v1.md) 为准。
4. 版本、响应封装和 CSRF 规则以 [api-versioning-v1.md](./api-versioning-v1.md) 为准。
5. 契约调整流程以 [contract-change-policy-v1.md](./contract-change-policy-v1.md) 为准。

## 2. 公共 API 范围

### 2.1 学习与推荐 API

机器契约：[learning-api-v1.yaml](./openapi/learning-api-v1.yaml)，服务根路径 `/api`。

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/learning/profile` | 获取当前学生知识点掌握情况 |
| `GET` | `/learning/weakness` | 获取当前学生薄弱知识点诊断 |
| `GET` | `/recommendation/path` | 获取当前学生个性化学习路径 |
| `POST` | `/recommendation/refresh` | 幂等刷新当前学生学习路径 |
| `GET` | `/admin/learning/student/{student_id}/profile` | 教师查看授权学生画像 |
| `GET` | `/admin/learning/class/knowledge-stats` | 教师查看授权班级知识点统计 |

### 2.2 Agent Run API

机器契约：[agent-api-v1.yaml](./openapi/agent-api-v1.yaml)，服务根路径 `/api/agent/v1`。

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/runs` | 创建四类 Agent 运行 |
| `GET` | `/runs/{run_id}` | 查询运行状态和结果 |
| `POST` | `/runs/{run_id}/feedback` | 创建或更新结果评价 |

冻结的 `service_type` 为：

- `submission_feedback`：个性化提交反馈。
- `code_explanation`：代码解读与优化分析。
- `socratic_hint`：苏格拉底式分层提示。
- `learning_path_explanation`：学习路径解释。

### 2.3 题目导入 API

机器契约：[problem-import-api-v1.yaml](./openapi/problem-import-api-v1.yaml)，服务根路径 `/api/admin/problem-import`。

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/batches` | 上传 QDUOJ-compatible ZIP 并异步校验 |
| `GET` | `/batches/{batch_id}` | 查询批次状态和汇总 |
| `GET` | `/batches/{batch_id}/problems` | 游标分页查询批次题目 |
| `GET` | `/batches/{batch_id}/errors` | 游标分页查询校验和导入问题 |
| `POST` | `/batches/{batch_id}/commit` | 幂等提交已校验题目 |

## 3. Agent 内部工具契约

四类 Agent 只能调用注册表白名单中的工具。冻结工具共 17 个：

1. `get_student_profile(user_id)`
2. `get_weak_points(user_id)`
3. `get_learning_path(user_id)`
4. `get_problem_info(problem_id)`
5. `get_problem_summary(problem_id)`
6. `get_problem_knowledge(problem_id)`
7. `get_knowledge_context(problem_id)`
8. `get_knowledge_dependencies(knowledge_id)`
9. `get_submission(submission_id)`
10. `get_student_recent_submissions(user_id, problem_id)`
11. `get_student_problem_history(user_id, problem_id)`
12. `get_error_patterns(problem_id, code_snippet, verdict)`
13. `search_error_patterns(code_snippet, verdict, problem_id)`
14. `get_algorithm_template(problem_id)`
15. `search_rag(...)`
16. `get_hint_level(user_id, problem_id)`
17. `save_agent_conversation(user_id, problem_id, message)`

每类 Agent 的精确参数、结果 Schema、可用工具矩阵和禁止工具见 [Agent 工具详细契约](./agent-tool-contract-v1.md#5-工具详细契约)。工具不得绕过认证上下文查询其他用户数据，不得返回隐藏测试点、标准答案或教师私有内容。

## 4. 公共协议规则

### 4.1 认证和权限

- 公共 API 复用现有 Django Session/Cookie 认证。
- 状态变更请求必须执行 CSRF 校验。
- `user_id`、教师身份、管理员身份和授权范围来自认证上下文，不接受客户端伪造。
- 教师查询必须落在活动教学班授权范围内。
- Agent 工具每次调用和缓存命中都必须重新执行权限检查。

### 4.2 幂等和分页

- 创建 Agent Run、刷新学习路径和提交导入批次使用 `Idempotency-Key`。
- 相同主体、端点、幂等键和请求体返回同一业务结果；请求体变化返回冲突。
- 批量题目和错误列表使用不透明游标分页。
- 分页 `limit` 范围为 1～500，默认 100。

### 4.3 响应、版本和错误

- 成功响应使用稳定 envelope，并返回 `X-API-Version: 1.0.0`。
- 错误响应统一包含 `code`、`message`、`details` 和 `request_id`。
- API、Agent 工具、学习工作流和 Management Command 使用同一错误码语义。
- 模型、RAG、Elo、Judge 等尚未就绪时返回明确的 dependency-not-ready 错误，不临时改变接口结构。

### 4.4 安全边界

- 不向学生返回完整解答、隐藏测试点、测试文件路径和教师私有题解。
- 学生代码不写入通用日志或向量库；审计只保存必要的哈希和长度。
- 教师端无权访问与资源不存在使用一致的外部语义，避免泄露学生和班级存在性。
- Agent 输出执行长度、内容、敏感字段和提示注入检查。

## 5. 机器契约附件

| 附件 | 标准用途 |
|---|---|
| [learning-api-v1.yaml](./openapi/learning-api-v1.yaml) | Swagger 展示、OpenAPI 校验和学习接口代码生成 |
| [agent-api-v1.yaml](./openapi/agent-api-v1.yaml) | Swagger 展示、OpenAPI 校验和 Agent API 代码生成 |
| [problem-import-api-v1.yaml](./openapi/problem-import-api-v1.yaml) | Swagger 展示、OpenAPI 校验和题目导入接口代码生成 |
| [agent-tool-contract-v1.md](./agent-tool-contract-v1.md) | Runtime 工具注册表、参数和权限契约 |
| [api-error-codes-v1.md](./api-error-codes-v1.md) | 统一错误码目录 |
| [api-versioning-v1.md](./api-versioning-v1.md) | 版本、响应和 CSRF 规则 |
| [contract-change-policy-v1.md](./contract-change-policy-v1.md) | 契约变更和升级流程 |

## 6. 验收标准

“确定接口契约”任务满足以下条件即视为完成：

- 三个 OpenAPI 文档均为 1.0.0，能够通过标准 OpenAPI 校验。
- 14 个公共端点的请求、响应、状态码、权限和幂等规则无待定项。
- 四类 Agent 的工具白名单、参数签名和输出安全边界已经冻结。
- 错误码、版本、CSRF、游标分页和依赖未就绪语义一致。
- 数据结构、OpenAPI 和批量交付契约使用一致的标识及枚举。

当前 1.0.0 版本满足上述文档与机器契约验收条件。冻结不代表 Django URL、View、Serializer、Dramatiq Worker 或 Agent Runtime 已经实现。
