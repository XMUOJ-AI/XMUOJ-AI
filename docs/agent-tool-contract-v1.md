# XMUOJ-AI Agent 工具接口契约

- 契约版本：1.0.0
- 状态：已批准／冻结
- 更新日期：2026-08-09
- 适用范围：第一期受控 Agent 工具层与 Agent Run API
- 上游设计基线：项目 Leader《技术路线与功能实现设计》Agent 部分
- 关联规范：[数据库结构](./data-model-v1.md)、[统一错误码](./api-error-codes-v1.md)、[Agent OpenAPI](./openapi/agent-api-v1.yaml)、[学习工作流 OpenAPI](./openapi/learning-api-v1.yaml)

## 1. 契约目标与对齐原则

本契约逐项采用飞书文档规定的工具名称、参数名称和参数顺序。工具注册表、Prompt 中的工具名、审计日志中的 `tool_name` 和契约测试必须使用本文件中的原名，不得自行替换为同义名称。

四类 Agent：

- `learning_path_explanation`：学习路径分析与推荐解释 Agent。
- `submission_feedback`：基于 RAG 的个性化编程反馈与学习引导 Agent。
- `socratic_hint`：苏格拉底式解题思路引导 Agent。
- `code_explanation`：提交代码解读与优化分析 Agent。

核心边界：

> 工作流负责知识点掌握度、薄弱点和学习路径的计算；Agent 只能通过飞书规定的受控工具读取或记录必要信息，并负责解释和引导。

### 1.1 学生输出政策（2026-10-12 确认）

四类 Agent 默认只提供自然语言解释、提示及文字步骤式伪代码，不输出可执行代码片段、完整解答或复制的修复代码。代码解读保留对本人提交的分析、复杂度和改进方向，以 `code_refs` 引用行号。变量名、数学式和复杂度记法可以保留；“读取两个数后比较大小”属于文字步骤，实际输入/输出函数或赋值语句不属于允许的伪代码。

自由文本范围：反馈的 `verdict_summary`、`likely_causes[].cause/check_first`、`next_question`；代码解读的 `summary`、`sections[].title/explanation`、`complexity.assumptions`、`improvement_directions`；提示的 `question/focus`；路径解释的 `overview`、`steps[].reason`、`next_action`。这些文本以及复杂度和引用字符串均接受服务端独立检查，不能把代码藏在其它字段。路径标识、步骤顺序、提示层级、行号引用等原结构约束继续有效。

`contains_full_solution=false` 仅为兼容字段，不能作为安全或审核证明。服务端对无围栏顶层程序、代码结构、调用/赋值、代码围栏、常见编码及 JSON 包装进行保守阻断；复杂或不符合允许格式的输出失败关闭，返回 `AGENT_OUTPUT_BLOCKED`，不交付部分结果。发布、GET、缓存与幂等重放都复检，旧 `passed` 标记不能绕过新规则。

已有 `approved` 错误模式和 `active` RAG 资料边界保留，算法模板只提供自然语言策略和复杂度，审核状态不自动豁免代码限制。教学代码片段另需人工审核规则；本期不新增代码审核工作流或发布能力。teacher/admin 原文可以保存但不进入学生检索。规则可能保守误拦，不承诺任意语言、混淆或自然语言答案的绝对防漏；真实模型与教学资料仍需人工验收。

## 2. 标识、鉴权与调用上下文

### 2.1 标识语义

| 字段 | 类型 | 语义 |
|---|---|---|
| `user_id` | integer | XMUOJ 用户数据库主键 |
| `problem_id` | string | XMUOJ `Problem._id` 展示编号，例如 `P305` |
| `submission_id` | string | XMUOJ Submission 文本主键 |
| `knowledge_id` | integer | `KnowledgePoint` 数据库主键 |

工具适配器负责把 `problem_id` 转换为内部 Problem 主键。对外工具不得把同一个 `problem_id` 有时解释为数据库整数、有时解释为展示编号。

### 2.2 `ToolContext`

Runtime 为每次工具调用注入：

```json
{
  "request_id": "req_01JEXAMPLE",
  "run_id": "45c1f7e8-8844-4cc1-a508-74ac31ce132a",
  "user_id": 1001,
  "service_type": "socratic_hint",
  "scopes": ["problem:read", "learning:self:read", "conversation:self:write"]
}
```

飞书签名中的 `user_id` 必须保留。Runtime 在调用前执行以下规则：

1. `arguments.user_id` 必须等于 `ToolContext.user_id`。
2. 不相等时返回 `AGENT_TOOL_PERMISSION_DENIED`，不得查询数据库。
3. `run_id`、权限、管理员状态和 RAG `access_scope` 只能来自 `ToolContext`。
4. 教师或管理员业务查询使用确定性管理接口，不通过学生 Agent 工具越权查询。

## 3. 通用工具结果

成功结果：

```json
{
  "ok": true,
  "data": {},
  "meta": {
    "schema_version": "1.0.0",
    "source_version": "2026-08-09T10:00:00Z",
    "cached": false,
    "truncated": false
  }
}
```

失败结果：

```json
{
  "ok": false,
  "error": {
    "code": "AGENT_TOOL_PERMISSION_DENIED",
    "message": "无权读取该数据",
    "retryable": false,
    "details": {}
  }
}
```

工具异常必须由 Runtime 转成统一结果；堆栈、数据库错误、内部路径和凭证只写入受控服务端日志。

## 4. 飞书规定的工具注册表

### 4.1 学习路径分析与推荐解释 Agent

以下签名必须原样注册：

```text
get_student_profile(user_id)
get_weak_points(user_id)
get_learning_path(user_id)
get_problem_info(problem_id)
get_knowledge_dependencies(knowledge_id)
search_rag(query, knowledge_id)
```

### 4.2 个性化编程反馈与学习引导 Agent

```text
get_problem_summary(problem_id)
get_error_patterns(problem_id, code_snippet, verdict)
get_algorithm_template(problem_id)
get_knowledge_context(problem_id)
get_student_recent_submissions(user_id, problem_id)
search_rag(query, problem_id, knowledge_id)
```

### 4.3 苏格拉底式解题思路引导 Agent

```text
get_problem_info(problem_id)
get_problem_knowledge(problem_id)
get_student_profile(user_id)
search_rag(query, problem_id, knowledge_id)
get_hint_level(user_id, problem_id)
save_agent_conversation(user_id, problem_id, message)
```

### 4.4 提交代码解读与优化分析 Agent

```text
get_submission(submission_id)
get_problem_info(problem_id)
get_problem_knowledge(problem_id)
get_algorithm_template(problem_id)
search_error_patterns(code_snippet, verdict, problem_id)
get_student_problem_history(user_id, problem_id)
search_rag(query, problem_id, knowledge_id)
```

## 5. 工具详细契约

所有参数对象均执行 `additionalProperties=false`。除飞书签名列出的参数外，模型不得传入 `limit`、`top_k`、`scope`、`role` 等额外参数；这些限制由服务端配置控制。

### 5.1 `get_student_profile(user_id)`

参数：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `user_id` | integer | 是 | 必须等于 `ToolContext.user_id` |

返回 `data`：

```json
{
  "user_id": 1001,
  "algorithm_version": "elo-v1",
  "updated_time": "2026-08-09T10:00:00Z",
  "knowledge_states": [
    {
      "knowledge_id": 12,
      "knowledge_code": "bfs_basic",
      "name": "BFS 基础遍历",
      "rating": 1040,
      "mastery_level": "learning",
      "confidence": 0.72
    }
  ]
}
```

只返回当前学生数据，最多 100 条；无状态记录时返回空数组。

### 5.2 `get_weak_points(user_id)`

参数：`user_id: integer`，必须等于 `ToolContext.user_id`。

返回 `data`：

```json
{
  "user_id": 1001,
  "algorithm_version": "elo-v1",
  "weak_points": [
    {
      "knowledge_id": 18,
      "knowledge_code": "grid_bfs",
      "name": "网格图 BFS",
      "rating": 980,
      "reason_codes": ["low_rating", "recent_failures"]
    }
  ]
}
```

结果必须来自薄弱点诊断工作流；Agent 不得重新计算 rating 或自行认定薄弱点。服务端最多返回 10 条。

### 5.3 `get_learning_path(user_id)`

参数：`user_id: integer`，必须等于 `ToolContext.user_id`。

返回 `data`：

```json
{
  "user_id": 1001,
  "path_id": "2caf14d0-8fc8-4994-a637-d8a82baf79bc",
  "algorithm_version": "path-v1",
  "target": {
    "knowledge_id": 21,
    "knowledge_code": "bfs_shortest_path",
    "name": "BFS 最短路"
  },
  "steps": [
    {
      "order": 1,
      "knowledge_id": 3,
      "knowledge_code": "queue",
      "problem_id": "P101",
      "title": "队列基础",
      "problem_rating": 1050,
      "reason_code": "prerequisite_weak",
      "reason_text": "前置知识掌握不足"
    }
  ],
  "generated_time": "2026-08-09T10:00:00Z"
}
```

Agent 只能解释该结构，不能调整顺序、替换题目、增加步骤或触发路径刷新。

### 5.4 `get_problem_info(problem_id)`

参数：`problem_id: string`，长度 1～100，例如 `P305`。

返回 `data`：

```json
{
  "problem_id": "P305",
  "title": "迷宫可达性",
  "description": "给定一个迷宫……",
  "input_description": "……",
  "output_description": "……",
  "samples": [{"input": "...", "output": "..."}],
  "difficulty": 3,
  "time_limit_ms": 1000,
  "memory_limit_mb": 128,
  "tags": ["BFS", "图论"]
}
```

只允许读取当前用户可见题目；不返回隐藏测试点、测试文件地址、标准代码或教师私有题解。

### 5.5 `get_problem_summary(problem_id)`

参数：`problem_id: string`。

返回不超过 2000 字符的题目摘要：

```json
{
  "problem_id": "P305",
  "title": "迷宫可达性",
  "summary": "给定迷宫、起点和终点，判断可达性。",
  "constraints_summary": "网格规模不超过 1000×1000",
  "difficulty": 3
}
```

### 5.6 `get_problem_knowledge(problem_id)`

参数：`problem_id: string`。

返回 `data`：

```json
{
  "problem_id": "P305",
  "knowledge_points": [
    {
      "knowledge_id": 18,
      "knowledge_code": "grid_bfs",
      "name": "网格图 BFS",
      "role": "primary",
      "weight": 1.0,
      "description": "在二维网格中使用 BFS 完成遍历。"
    }
  ]
}
```

只返回 active 且审核通过的题目—知识点映射。

### 5.7 `get_knowledge_context(problem_id)`

参数：`problem_id: string`。

返回题目知识点以及已审核的直接前置关系：

```json
{
  "problem_id": "P305",
  "knowledge_points": [],
  "prerequisites": [],
  "context_summary": "本题主要训练网格图 BFS，并依赖队列和基础遍历。"
}
```

`context_summary` 由确定性模板生成，不调用模型。

### 5.8 `get_knowledge_dependencies(knowledge_id)`

参数：`knowledge_id: integer`，大于 0。

返回 `data`：

```json
{
  "root": {
    "knowledge_id": 21,
    "knowledge_code": "bfs_shortest_path",
    "name": "BFS 最短路"
  },
  "prerequisites": [
    {
      "knowledge_id": 12,
      "knowledge_code": "bfs_basic",
      "name": "BFS 基础遍历",
      "relation_type": "required",
      "weight": 1.0
    }
  ]
}
```

按飞书用途只返回前置关系；最多 30 个节点，只返回审核通过的依赖。

### 5.9 `get_submission(submission_id)`

参数：`submission_id: string`，长度 1～64。

返回 `data`：

```json
{
  "submission_id": "abc123",
  "problem_id": "P305",
  "language": "C++",
  "code": "int main() { ... }",
  "code_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "verdict": "WA",
  "is_final": true,
  "time_cost_ms": 15,
  "memory_cost_bytes": 4194304,
  "compiler_message": null,
  "created_time": "2026-08-09T10:00:00Z"
}
```

只允许读取当前用户自己的提交。不得返回原始 `Submission.info` 或隐藏测试点；Pending/Judging 时 `is_final=false`，Runtime 不启动模型分析。

### 5.10 `get_student_recent_submissions(user_id, problem_id)`

参数顺序必须为 `user_id, problem_id`。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `user_id` | integer | 是 | 必须等于 `ToolContext.user_id` |
| `problem_id` | string | 是 | XMUOJ 展示编号 |

返回最近 5 次同题提交摘要，不返回完整历史代码：

```json
{
  "user_id": 1001,
  "problem_id": "P305",
  "attempt_count": 4,
  "recent_submissions": [
    {
      "submission_id": "abc123",
      "verdict": "WA",
      "language": "C++",
      "created_time": "2026-08-09T10:00:00Z"
    }
  ]
}
```

### 5.11 `get_student_problem_history(user_id, problem_id)`

参数和安全规则与 `get_student_recent_submissions` 相同，但用于代码分析上下文，额外返回：

```json
{
  "user_id": 1001,
  "problem_id": "P305",
  "attempt_count": 4,
  "accepted": false,
  "recent_submissions": [
    {
      "submission_id": "abc123",
      "verdict": "WA",
      "language": "C++",
      "created_time": "2026-08-09T10:00:00Z",
      "code_changed": true
    }
  ]
}
```

### 5.12 `get_error_patterns(problem_id, code_snippet, verdict)`

参数顺序必须与飞书一致：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `problem_id` | string | 是 | XMUOJ 展示编号 |
| `code_snippet` | string | 是 | 1～100000 字符，只在当前调用内使用 |
| `verdict` | string | 是 | `WA`、`TLE`、`MLE`、`RE`、`CE` |

返回 `data`：

```json
{
  "patterns": [
    {
      "code": "BFS_VISITED_TOO_LATE",
      "cause_short": "visited 标记时机过晚",
      "fix_direction": "检查节点是否在入队时立即标记。",
      "confidence": 0.78,
      "source": "reviewed"
    }
  ]
}
```

只返回审核通过的错误模式；不得返回可直接复制的完整修复代码。

### 5.13 `search_error_patterns(code_snippet, verdict, problem_id)`

参数顺序必须为 `code_snippet, verdict, problem_id`，与 `get_error_patterns` 不同。

检索逻辑可以结合规则、关键词或向量相似度；返回结构与 `get_error_patterns` 一致。代码片段不得写入通用日志或向量库，审计仅保存代码哈希和长度。

### 5.14 `get_algorithm_template(problem_id)`

参数：`problem_id: string`。

返回经教师审核且已移除完整解答细节的算法模板：

```json
{
  "problem_id": "P305",
  "algorithm_template": "使用队列进行 BFS，维护 visited 和 distance 状态。",
  "complexity_target": {"time": "O(nm)", "space": "O(nm)"},
  "contains_full_solution": false,
  "source_ids": ["rag_doc_123"]
}
```

不得直接读取或返回 XMUOJ `Problem.template` 中可能存在的完整标准代码。

### 5.15 `search_rag`

飞书为不同 Agent 定义了两个精确签名。Runtime 必须按 `service_type` 注册对应参数 Schema。

学习路径解释：

```text
search_rag(query, knowledge_id)
```

其他三类 Agent：

```text
search_rag(query, problem_id, knowledge_id)
```

参数：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `query` | string | 是 | 1～500 字符 |
| `problem_id` | string | 对三参数签名是 | 当前用户可见题目 |
| `knowledge_id` | integer | 是 | 大于 0 |

返回 `data`：

```json
{
  "hits": [
    {
      "chunk_id": "9f58ed7f-9d6a-4c3e-a366-4189f373a63a",
      "source_type": "textbook",
      "title": "BFS 基础",
      "excerpt": "BFS 使用队列按距离从小到大扩展……",
      "score": 0.83
    }
  ],
  "retrieval_version": "bge-m3-v1"
}
```

服务端固定 `top_k<=5`，强制追加 `status=active` 和当前用户访问范围过滤；不允许模型自行传入过滤范围。

### 5.16 `get_hint_level(user_id, problem_id)`

参数顺序必须为 `user_id, problem_id`；`user_id` 必须等于认证上下文。

返回 `data`：

```json
{
  "user_id": 1001,
  "problem_id": "P305",
  "hint_level": 1,
  "max_hint_level": 3,
  "hint_available": true,
  "hint_available_time": "2026-08-09T10:03:00Z",
  "student_explanation_required": true,
  "student_explanation_received": true
}
```

### 5.17 `save_agent_conversation(user_id, problem_id, message)`

参数顺序必须与飞书一致：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---:|---|
| `user_id` | integer | 是 | 必须等于 `ToolContext.user_id` |
| `problem_id` | string | 是 | 当前会话题目 |
| `message` | string | 是 | 1～16000 字符 |

返回 `data`：

```json
{
  "message_id": 9001,
  "saved": true,
  "created_time": "2026-08-09T10:03:10Z"
}
```

会话 ID、消息角色、Run ID 和提示层级由 Runtime 根据当前 Run 注入，模型不能指定。该工具只能向当前用户、当前题目、当前活跃会话追加消息，不能覆盖或删除历史记录。

## 6. 工具可用性矩阵

| 工具 | learning_path_explanation | submission_feedback | socratic_hint | code_explanation |
|---|:---:|:---:|:---:|:---:|
| `get_student_profile(user_id)` | ✓ | - | ✓ | - |
| `get_weak_points(user_id)` | ✓ | - | - | - |
| `get_learning_path(user_id)` | ✓ | - | - | - |
| `get_problem_info(problem_id)` | ✓ | - | ✓ | ✓ |
| `get_knowledge_dependencies(knowledge_id)` | ✓ | - | - | - |
| `get_problem_summary(problem_id)` | - | ✓ | - | - |
| `get_error_patterns(problem_id, code_snippet, verdict)` | - | ✓ | - | - |
| `get_algorithm_template(problem_id)` | - | ✓ | - | ✓ |
| `get_knowledge_context(problem_id)` | - | ✓ | - | - |
| `get_student_recent_submissions(user_id, problem_id)` | - | ✓ | - | - |
| `get_problem_knowledge(problem_id)` | - | - | ✓ | ✓ |
| `get_hint_level(user_id, problem_id)` | - | - | ✓ | - |
| `save_agent_conversation(user_id, problem_id, message)` | - | - | ✓ | - |
| `get_submission(submission_id)` | - | - | - | ✓ |
| `search_error_patterns(code_snippet, verdict, problem_id)` | - | - | - | ✓ |
| `get_student_problem_history(user_id, problem_id)` | - | - | - | ✓ |
| `search_rag(query, knowledge_id)` | ✓ | - | - | - |
| `search_rag(query, problem_id, knowledge_id)` | - | ✓ | ✓ | ✓ |

生产 Tool Registry 必须按 `service_type` 使用白名单注册；矩阵中 `-` 的工具不得被该 Agent 调用。

## 7. 飞书规定的禁止工具

### 7.1 学习路径解释 Agent

```text
update_student_rating()
modify_learning_path()
generate_learning_path()
modify_problem_knowledge()
modify_knowledge_graph()
```

### 7.2 个性化编程反馈 Agent

```text
update_student_rating()
modify_learning_path()
modify_knowledge_graph()
publish_problem()
change_problem_knowledge()
```

### 7.3 苏格拉底式引导 Agent

```text
get_full_solution_code()
get_hidden_testcases()
modify_submission()
generate_final_answer()
```

### 7.4 代码分析 Agent

```text
get_hidden_testcases()
get_full_standard_code()
modify_submission()
submit_code_for_student()
```

以上名称不得出现在对应 Agent 的生产 Tool Registry。任何 Agent 均不得获得修改评分、学习路径、知识图谱、题目、提交或代替学生提交代码的能力。

## 8. Runtime 内部能力

Runtime 可以在实现内部聚合多个读取调用、记录 ToolCall、更新调用额度和执行安全检查，但这些内部函数不得注册为新的 LLM 工具，也不得改变第 4 节的工具名与参数签名。

提示层级提升由确定性 Runtime 事件处理；Agent 只能通过 `get_hint_level` 读取，通过 `save_agent_conversation` 追加当前会话消息。

## 9. Agent Run 公共 API

公共 HTTP API 保持：

```text
POST /api/agent/v1/runs
GET  /api/agent/v1/runs/{run_id}
POST /api/agent/v1/runs/{run_id}/feedback
```

请求、响应、状态码和字段 Schema 以 `docs/openapi/agent-api-v1.yaml` 为准。内部 Agent 工具不直接暴露为普通 HTTP API，前端不得绕过 Runtime 调用工具。

学生画像和推荐路径工作流 API 以 `docs/openapi/learning-api-v1.yaml` 为准。Agent 可以读取相同领域服务，但不得调用 `POST /api/recommendation/refresh`。

## 10. 缓存与幂等

Run 输入哈希至少包含：

- `user_id`、`service_type`。
- `problem_id` 或 `submission_id`。
- 提交代码 SHA-256 与 verdict。
- 知识点、画像或路径数据版本。
- `prompt_version` 和模型配置版本。
- 用户可影响输出的 options。

缓存策略：

| 服务 | 默认缓存键 |
|---|---|
| submission_feedback | submission_id + verdict + code hash + prompt version |
| code_explanation | submission_id + code hash + prompt version |
| socratic_hint | user_id + problem_id + hint level + student input hash |
| learning_path_explanation | user_id + path_id + path version + prompt version |

缓存命中仍必须重新进行用户、题目和提交的对象级权限检查。

## 11. 调用预算与超时

单次 Run 默认限制：

- 工具调用总数最多 8 次。
- `search_rag` 最多 2 次，每次最多返回 5 个片段。
- 工具累计上下文最多 30 KiB。
- 用户代码最多 100 KiB 进入模型。
- 模型输出最多 2000 tokens。
- Run 超时 30 秒。
- 同一用户并发 Run 最多 2 个，每分钟最多创建 6 个。

超限返回 `AGENT_BUDGET_EXCEEDED` 或 `AGENT_RATE_LIMITED`。

## 12. 输出安全要求

模型输出写入 `AgentRun.output_payload` 前必须检查：

- 是否包含完整可运行解答或完整标准代码。
- 是否声称读取了隐藏测试点。
- 是否包含其他用户数据。
- 是否包含系统 Prompt、密钥、内部路径或服务地址。
- 是否符合对应 `service_type` 的输出 Schema。
- 是否承诺直接替学生修改或提交代码。

检测到违规输出时，Runtime 必须阻断或脱敏，不得把原始违规内容返回学生。

## 13. 版本与变更管理

- 飞书文档是工具名称和签名的上游基线。
- 修改工具名、参数名、参数顺序或必填性必须先更新飞书并由 Leader 确认。
- 新增工具必须先加入飞书对应 Agent 的可调用工具清单，再更新本契约。
- 每次 ToolCall 记录 `tool_name`、`tool_version` 和 `service_type`。
- 删除字段或修改字段含义必须升级主版本。

## 14. 第一期实现范围

第一期必须冻结并实现第 4 节全部工具 Schema。依赖尚未完成时，允许工具返回 `AGENT_DEPENDENCY_NOT_READY`，但不得改名或换成其他参数签名。

MVP 顺序遵循飞书：

1. 编程反馈覆盖前 20 道高频题的 WA/TLE/RE 错误模式、题目摘要和算法模板。
2. 代码分析支持 AC 复杂度与优化建议、WA/TLE/RE 引导和 CE 编译信息解释。
3. 苏格拉底提示支持思考计时、学生题意自述和 3 层提示。
4. 学习路径 Agent 只解释工作流生成的路径，不重新生成或修改路径。
5. 所有 Agent 调用具备日志、反馈、缓存、限流和安全检查。

## 15. 契约测试清单

### 15.1 注册表快照测试

每个 `service_type` 必须断言注册的工具名和参数顺序与第 4 节完全相同；不允许额外工具、别名或缺失工具。

### 15.2 工具通用测试

每个工具至少覆盖：

1. 正常结果符合 Schema。
2. 缺少参数、参数顺序映射错误或出现额外参数。
3. `arguments.user_id` 与认证上下文不一致。
4. 不可见题目、其他用户提交或会话。
5. Pending/Judging 提交。
6. RAG、Elo、知识图谱依赖未就绪。
7. 缓存命中仍进行权限检查。
8. 输出不含隐藏测试点、完整答案和敏感字段。
9. 禁止工具无法被模型发现或调用。
10. `problem_id` 始终按 XMUOJ 展示编号处理。

端到端链路：

```text
创建 Agent Run
-> 根据 service_type 加载飞书规定的工具白名单
-> 校验参数和 ToolContext
-> 调用领域服务
-> 记录 ToolCall
-> 生成并执行输出安全检查
-> 查询 Run 得到结构化结果
-> 重复请求命中缓存
-> 用户提交反馈
```
