# Agent 服务实施说明

此模块实现旧契约的三条 Run/Feedback API 与必要的会话入口，共四条；工具保持 17 个唯一名称、18 组签名，不能直接通过 HTTP 调用。`contracts.py` 明确列出每类服务的白名单；`api_schemas.json` 是 working OpenAPI 的 JSON Schema 转换副本，nullable 转为显式 null 类型，构建过程不引入生产 YAML 依赖。

运行链路为 Session + CSRF → 受控输入与对象权限 → 同用户 PostgreSQL 事务锁 → AgentRun 和 AgentDispatch 同事务入库 → Dramatiq Redis 队列 → 真实模型 HTTP 工具循环 → Schema、权限、来源版本和安全检查 → 结构化结果。缓存只复用原始模型运行，在 30 分钟内有效，并重新验证账号、题目、本人提交、当前路径、检索资料和工具实际读取的引用。代码仅在调用时读取本人 Submission；input_payload 存代码哈希/语言/verdict，不复制完整源码。工具审计保存敏感参数的哈希与长度和结果摘要；不记录 provider 原始错误。

新增 `/api/agent/v1/conversations` 以 `{"problem_id":"P001","service_type":"socratic_hint"}` 创建或返回本人活动会话，HTTP 201/200，重复不会重置倒计时。默认等待 180 秒；每次请求必须含自己的解题思路，成功发布后才增加提示级别，共三级。任何模型工具都不能调整层级、评分、学习路径或提交代码。

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

安全检查是确定性的结构校验、权限过滤、敏感串和完整代码模式阻断，并辅以系统约束；它不是对任意自然语言输出的形式化正确性证明。不得用测试通过替代真实供应商、真实语料和最终人工验收。
