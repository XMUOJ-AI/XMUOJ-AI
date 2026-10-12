# Agent 服务实施说明

此模块实现旧契约的三条 Run/Feedback API 与必要的会话入口，共四条；工具保持 17 个唯一名称、18 组签名，不能直接通过 HTTP 调用。`contracts.py` 明确列出每类服务的白名单；`api_schemas.json` 是 working OpenAPI 的 JSON Schema 转换副本，nullable 转为显式 null 类型，构建过程不引入生产 YAML 依赖。

运行链路为 Session + CSRF → 受控输入与对象权限 → 同用户 PostgreSQL 事务锁 → AgentRun 和 AgentDispatch 同事务入库 → Dramatiq Redis 队列 → 真实模型 HTTP 工具循环 → Schema、权限、来源版本和安全检查 → 结构化结果。缓存只复用原始模型运行，在 30 分钟内有效，并重新验证账号、题目、本人提交、当前路径、检索资料和工具实际读取的引用。代码仅在调用时读取本人 Submission；input_payload 存代码哈希/语言/verdict，不复制完整源码。工具审计保存敏感参数的哈希与长度和结果摘要；不记录 provider 原始错误。

新增 `/api/agent/v1/conversations` 以 `{"problem_id":"P001","service_type":"socratic_hint"}` 创建或返回本人活动会话，HTTP 201/200，重复不会重置倒计时。默认等待 180 秒；每次请求必须含自己的解题思路，成功发布后才增加提示级别，共三级。任何模型工具都不能调整层级、评分、学习路径或提交代码。

## 学生输出政策

默认只提供提示、自然语言解释和文字步骤式伪代码。代码解读仍可解释本人提交的意图、错误、复杂度和改进方向，通过 `code_refs` 引用行号；不复制源码，也不输出修复代码。变量名、数学式、`O(n log n)` 等复杂度和 `L1-L3` 行号可保留。文字伪代码例如“队列非空时取出首项，再检查未访问的邻居”，不能用实际语言的赋值、调用、循环语法冒充伪代码。

| Agent | 可生成的自然语言字段 | 保持结构或来源约束的字段 |
| --- | --- | --- |
| submission_feedback | verdict_summary、likely_causes[].cause/check_first、next_question | confidence、knowledge_refs；引用文本也经过安全检查 |
| code_explanation | summary、sections[].title/explanation、complexity.assumptions、improvement_directions | code_refs仅行号；complexity.time/space仅复杂度说明 |
| socratic_hint | question、focus | hint_level由服务端确认，next_hint_available_at由服务端生成 |
| learning_path_explanation | overview、steps[].reason、next_action | path_id及所有步骤的order/knowledge_code必须保持已有路径 |

所有文本字段都经过同一检查。`contains_full_solution=false` 是保留的兼容字段，不是模型的安全证明或审核凭据。检查不只查 `main`/`solve`：无围栏的顶层 Python、常见语言代码结构、调用/赋值、代码围栏、嵌套 JSON 字符串和常见编码伪装都会被拒绝。无法安全展示的内容整份阻断，返回 `AGENT_OUTPUT_BLOCKED`，不发布部分结果，也不推进提示层级。裸标识符或单独数学式不会仅因可被 Python AST 解析就认定为代码。

审核后的 ErrorPattern、RAG 策略和复杂度工具结果继续使用现有 `approved`/`active` 与权限边界，审核状态不提供代码豁免。教学代码片段需另有人工审核规则；当前未建设独立审核/发布流程，因此学生输出默认拒绝这类代码。teacher/admin 范围原文可保留，用于管理与后续审核，不进入学生检索。

输出发布、查询、幂等重放及缓存读取都重新执行政策检查。旧不安全结果不会因已标记 `passed` 而直接返回；新幂等键会跳过不安全缓存，创建新的运行。提示版本已更新为 `agent-v2-hints-only`，避免继续复用旧提示词的缓存。

## 配置和运行

- `AGENT_MODEL_URL`：完整 HTTP(S) chat-completions 协议地址；`AGENT_MODEL_NAME` 必填；`AGENT_MODEL_API_KEY` 可选 Bearer 凭证。未配置返回 `AGENT_DEPENDENCY_NOT_READY`，运行中供应商失败返回可重试错误，不填充假答案。
- `AGENT_MODEL_CONFIG_VERSION`：默认 `v1`，供应商参数或政策变更时递增以使缓存失效。`AGENT_THINK_SECONDS` 默认 `180`。
- 模型协议：POST JSON 的 `model/messages/tools/tool_choice/response_format/max_tokens/temperature`；返回 `choices[0].message`（`content` JSON 字符串或 `tool_calls`）及可选 `usage.prompt_tokens/completion_tokens`。必须支持受控 function calling 与 JSON 结果。没有 usage 时审计计数保持 0，表示供应商未报告；它不是估算 token 数。输出同时执行确定性词元上限检查。
- `python manage.py rundramatiq --queues agent` 启动实际 worker。独立进程运行 `python manage.py dispatch_agent_runs`，由运维调度器周期调用（建议每分钟）；它重发超过 60 秒未启动的队列意图，并将失联的 running 运行标为可重试超时。重复队列消息不会再次执行已认领运行。调用者使用新幂等键重试失败运行。
- 数据库迁移 `agent_service/0001_initial.py` 含六个基线对象以及 AgentDispatch outbox。追加字段 request_hash 区分幂等请求与缓存上下文；conversation 关联冻结实际会话；error_retryable、feedback.updated_time 服务于已有响应契约。
- 手工审核错误模式通过 `python manage.py import_error_patterns patterns.json --author <用户ID> --reviewer <另一超级管理员ID>` 入库。两人均须启用；文件为 1～1000 项数组，单项字段为 code、problem_id（展示编号）或 knowledge_id、verdict、cause_short、fix_direction，可选 cause_detail/retrieval_text/priority。导入持有知识写锁，知识须 active，学生输出字段须安全。Agent 只有读取能力。
- RAG 的实际 Milvus/embedding 配置、入库和重建命令见 [RAG README](../rag/README.md)。没有真实审核语料时检索返回空结果或模板未就绪，不生成占位教学内容；前 20 道高频题的真实错误模式仍须由教师提供并审核。

## 验证边界

`python manage.py test agent_service rag --settings=oj.settings` 使用 PostgreSQL 测试库。模型 HTTP 测试服务器和内存返回值只定义在测试文件中，不存在生产假模型开关。独立 Redis namespace 测试实际生产调度链使用的 actor/worker 协议；HTTP fixture 校验模型协议、真实 RAG embedding/Milvus REST 传输与错误边界，但没有把 fixture 宣称为已连通学校模型/Milvus生产实例。

权限和来源撤回在模型调用前、输出发布前、GET 和缓存/幂等重放时复核。数据库与外部模型不能共享事务；网络期间变化会使结果失败、要求重新运行。所有工具调用总数最多 8、RAG 最多 2、累计工具数据 30KiB、本人代码 100KiB、输出 2000 tokens、运行总时限 30 秒，同用户并发 2、每分钟创建 6。来源指纹按当前问题/路径/个人画像范围读取，不在每次 POST 载入全站映射。

安全检查采用保守的结构校验、权限过滤、敏感串及代码语法/结构识别，并辅以系统约束。可能把类似代码的解释拒绝；应改写为自然语言或行号引用。它不保证识别任意语言、任意混淆，也不能证明自然语言内容在教学上正确；不得用测试通过替代真实供应商、真实语料和最终人工验收。
