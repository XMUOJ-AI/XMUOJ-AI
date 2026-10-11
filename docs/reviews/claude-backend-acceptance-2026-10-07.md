# Claude 独立后端验收记录（2026-10-07）

验收对象：`/Users/jingweihao/大创/XMUOJ-AI`，分支 `duduking19`，基线 `144410a`，全部改动未提交。范围为完整后端（知识审批、题包导入、学习/班级、RAG、四类 Agent 及旧 OJ 回归，34 个 HTTP 操作、17 个工具名/18 种签名）。新增前端页面、真实模型/Embedding/Milvus/JudgeServer 部署不在本轮范围内。

依据：`docs/project` 原件、`docs/openapi` 与 `docs/schemas` 工作契约、`docs/knowledge/implementation-notes-2026-10-07.md`、第一轮证据（完成矩阵、`backend-acceptance-2026-10-07.md`、`backend-development.md`）及实际源码。原交付稿 `docs/knowledge/review-v0.9.9`、资料归档、旧库均未修改；未提交、未推送。

## 结论

**后端有条件通过验收。** 第一轮结论可复现：270 项 Django 全库测试、lint、迁移检查、契约校验、健康检查单测均独立重跑通过。本轮发现 3 个明确缺陷并已修复回归，未发现剩余阻断项。下文“人工决策项”需负责人拍板，其中 H1（判题提交路径上的全局锁）建议在真实班级并发压测后再上线。

## 验收方法

1. 按模块通读新增代码：`utils/contract_api.py`、`knowledge`、`learning`、`problem_import`、`rag`、`agent_service`，以及旧 OJ 改动（`judge/dispatcher.py`、`submission/views/admin.py`、`account/views/admin.py`、部署脚本、nginx、settings）。
2. 重点核查空值、重复请求、并发、权限、超时、异常处理、敏感信息泄露七个方面。
3. 在 8001 开发服务上做未登录 HTTP 探测；在隔离开发库内做已登录边界探测（事务包裹，结束后回滚）。
4. 每项修复都补了回归测试，并临时还原修复代码，确认该测试在旧代码上失败、修复后通过。

## 七类重点核查结果

| 维度 | 结论 | 依据 |
| --- | --- | --- |
| 空值 | 通过 | 请求体为 `null`/数组/空参数时，learning、agent、import、knowledge 均返回契约内 400 envelope；`limit=null`、`class_id=null`、非 UUID run_id 均为 400，无 500。 |
| 重复请求 | 修复 1 项后通过 | Agent 运行/导入提交/路径刷新都有幂等键和请求指纹，键冲突返回 409；判题重复投递通过 advisory 锁和终态检查去重。**F2**：学习事件恢复会重复投递，已修复。 |
| 并发 | 通过（H1 待决） | 知识写入共用事务级 advisory 锁和行锁，DB 约束兜底（单 pending 批次、单 active 路径、无自环等）；Agent 按用户加锁，导入用 worker 会话锁。我推测的 Agent 反馈并发冲突经实测不存在（Django `update_or_create` 已兜底），未改动。 |
| 权限 | 修复 1 项后通过 | 新接口只认 Session 和 CSRF，不接受 APPKEY；知识审核仅限 Super Admin 且禁止自审；教师权限按班级成员判断，越界返回 404；管理员跨班需填审计理由并记录。**F1**：导入接口权限越界，已修复。 |
| 超时 | 修复 1 项后通过 | 模型/Embedding/Milvus 请求带总截止时间且禁止重定向，响应限 2 MiB；Agent 单次运行 30 秒，actor 35 秒，恢复进程把超过 60 秒的运行置为失败；判题请求 `(5,120)` 秒；advisory 锁等待 5 秒、语句 30 秒。**F3**：nginx 上传上限低于契约，已修复。 |
| 异常处理 | 通过 | `ContractAPIView` 统一转换为 envelope，500 只记录 request_id 和异常类型；学习事件捕获失败不影响判题落库，可由 backfill 补齐；导入失败会清理测试目录。 |
| 敏感信息 | 通过 | 历史 Sentry DSN 已移除；首个管理员密码从环境变量读取；外部服务异常和响应体不回显；工具调用日志只存代码/消息/查询的哈希和长度；输出过滤会拦截内网地址、本机路径、系统提示词和已配置密钥。 |

## 发现与整改（按执行顺序）

### F1 导入接口允许“无题目权限的管理员”创建题目（权限，已修复）

- 问题：`problem_import/views.py` 的 `AdminOnly` 只检查 `is_admin_role()`。旧 OJ 的 `problem_permission_required` 会拒绝 `problem_permission=NONE` 的 Admin，知识模块的 `require_admin` 也会拒绝；导入提交却能以该用户身份创建 Problem，形成越权。
- 实测：修复前，该类管理员访问批次返回 200（已登录探测：上传请求能进入参数校验阶段）。
- 整改：Super Admin 一律放行；Admin 必须 `problem_permission != NONE`，与旧题目接口保持一致。
- 回归：`ImportTests.test_api_permissions_csrf_cursor_and_commit` 新增该类用户返回 403 的断言；还原修复后失败（`200 != 403`），修复后通过。

### F2 学习恢复进程每 30 秒重复投递全部未处理事件（重复请求，已修复）

- 问题：Supervisor 每 30 秒运行一次 `recover_learning --backfill`，每轮把最多 1000 条非 processed 事件重新 `send`。worker 变慢或停机时，Redis 队列会每轮多出最多 1000 条重复消息。虽然处理是幂等的，但队列和全局锁的竞争会持续放大。
- 整改：异步重投只处理闲置超过 5 分钟的事件（大于 actor 重试退避上限），发送前刷新 `updated_time`，下一轮不会立刻再投。`--sync` 和 backfill 新建的事件不受影响，新建事件仍在提交后立即投递。
- 回归：`LearningRecoveryTests.test_async_redelivery_skips_recent_events_and_does_not_resend_each_pass`；还原修复后失败（新事件被立即重投），修复后通过。

### F3 nginx 200M 上传上限低于导入契约 256 MiB（超时/边界，已修复）

- 问题：`api_proxy.conf` 全局写死 `client_max_body_size 200M`，而契约和 `WEB_LIMIT` 都是 256 MiB。200 到 256 MiB 的合法数据包会被 nginx 用 HTML 413 拒绝，拿不到契约的 `IMPORT_SIZE_LIMIT` envelope。
- 整改：从 `api_proxy.conf` 移除该行。`/api` 保持 200M；新增 `location ^~ /api/admin/problem-import/`，上限 257m（预留 multipart 开销）。超过 256 MiB 的请求仍由 Django 的 `BoundedUploadHandler` 返回契约 413。
- 验证：在本地 `xmuoj-ai-local` 镜像里用真实 nginx 测试，210 MB 请求体发到导入路径会透传上游（无上游返回 502），发到其他 `/api` 路径仍返回 413。

## 实际验证命令与结果

均在 PostgreSQL `127.0.0.1:15432`、Redis `127.0.0.1:16379` 隔离环境执行，没有连接 8000 旧服务或其他数据库。

| 命令（目录） | 结果 |
| --- | --- |
| `POSTGRES_PORT=15432 REDIS_PORT=16379 ../.venv/bin/python manage.py test --settings=oj.settings --noinput`（backend，整改前基线） | **Ran 270 tests in 283.985s, OK，退出码 0** |
| 同上加 `--keepdb`（backend，整改后） | **Ran 271 tests in 263.285s, OK，退出码 0**（270 项加新增 1 项） |
| `POSTGRES_PORT=15432 REDIS_PORT=16379 ../.venv/bin/python manage.py test problem_import learning ... --keepdb` | Ran 50 tests, OK |
| `../.venv/bin/flake8 --statistics .`（backend） | 0 问题 |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py check --deploy` | 只有开发配置下的 HSTS、SSL 跳转、安全 Cookie、DEBUG 5 项警告，见 H6 |
| `.venv/bin/python tools/problem_batch/validate_contracts.py`（仓库根） | contract validation passed |
| `.venv/bin/python -m unittest discover -s backend/deploy -p test_health_check.py` | 8 tests OK |
| `.venv/bin/python -m unittest discover -s tools/problem_batch/tests` | 6 tests OK |
| 8001 未登录探测（5 个新模块入口） | 均为 401 JSON envelope，带 request_id |
| 已登录边界探测（开发库事务内，结束后回滚） | 见“七类重点核查结果”中的空值和权限两行 |

说明：首轮基线运行没有加 `--keepdb`，Django 重建了隔离 PG 中的 `test_onlinejudge` 测试库，没有触碰其他数据库；后续运行均使用 `--keepdb`。

## 残余人工决策项（未改动，需要负责人决定）

- **H1 判题结果提交路径上的全局锁。** 普通题判题落库时，`Submission` post_save 会同步调用 `capture_submission`，在判题事务内获取全局 `KNOWLEDGE_WRITE_LOCK` 和 `learning_rating:global` advisory 锁，直到事务提交才释放（判题事务还包括题目和用户统计重算）。学习 worker 的 `replay_user` 也持有这两把锁，并会全量重放该生到当前为止的历史。正确性有保障：拿锁超时 5 秒时只记录日志，后续由 backfill 补齐。但在实验课集中提交时，所有判题落库会被串行化，学习更新也可能大面积延迟。建议用真实班级规模压测后再决定，可选方向：把捕获改为只写 outbox、不拿全局锁，或把锁粒度降到题目/用户级。
- **H2 导入批次不按上传人隔离。** 任何有题目权限的 Admin（包括 `OWN`）都能查看、提交其他管理员上传的批次。契约原文是“仅允许已认证的管理员”。是否要按上传人或 `OWN` 范围隔离，需要决定。
- **H3 `X-Audit-Reason` 无法传中文。** HTTP 头只能是 ISO-8859-1，浏览器 fetch 直接拒绝非 Latin-1 头，curl 发送的 UTF-8 会被 Django 按 latin-1 解码成乱码写入审计。需要在契约层决定：限定 ASCII、改用 percent-encoding，还是改为 query/body 字段。
- **H4 批量导入用户的默认密码 `123456`。** 这是旧逻辑，本轮按原样保留。是否改为随机密码并导出，或强制首次登录改密，属于安全策略决定。
- **H5 公开知识点详情的 `related_problems` 不分页；RAG 的 PostgreSQL 检索在查询时临时计算 tsvector，没有索引。** 当前数据规模没有问题。题量或语料变大后，需要在契约层加分页，或建 GIN 表达式索引。
- **H6 生产安全头。** `check --deploy` 提示 HSTS、`SECURE_SSL_REDIRECT`、`SESSION_COOKIE_SECURE`、`CSRF_COOKIE_SECURE` 未设置。这取决于生产是否全站 HTTPS，属于部署决策。
- **H7 外部依赖仍是夹具/替身。** 模型、Embedding、Milvus 使用本地真实 HTTP 协议夹具，JudgeServer 使用替身；前端 `dist` 缺失，生产镜像没有从零构建。这与第一轮登记一致，不能视为已联通。

另记一处非阻断观察：lint 整理把 `judge/languages.py` 中 Go 模板的制表符改成了空格。Go 编译不受影响，但学生看到的模板缩进与 gofmt 风格不同，可按需还原。

## 本轮改动清单

- `backend/problem_import/views.py`：F1 权限修复。
- `backend/problem_import/tests.py`：F1 回归断言。
- `backend/learning/management/commands/recover_learning.py`：F2 重投节流。
- `backend/learning/tests.py`：F2 回归测试。
- `backend/deploy/nginx/api_proxy.conf`、`backend/deploy/nginx/locations.conf`：F3 按路径设置上传上限。
- 本文件。
