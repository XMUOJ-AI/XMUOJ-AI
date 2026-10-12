# 后端完整验收与整改记录（2026-10-12）

后续更新：用户已确认 D01–D04 的整改方向，最新实施与复验见[确认项整改与第二轮验收](backend-remediation-2026-10-12.md)。本报告保留首轮结论及当时的待决状态；D05/D06 已按用户要求暂缓。

**结论：首轮验收不通过；本轮已整改无需业务决策的确定缺陷，仍不能认定“原始需求全部完成”或“可以生产上线”。** 比赛重判计分、AI 完整答案防漏、依赖升级和真实环境验收仍是待处理边界。需要人工判断的事项已跳过，没有借技术整改擅自改变业务规则。

验收对象为 `XMUOJ-AI` 实际当前分支 **`duduking19`，起点 `e5341ee`**；用户所称 duduking 与项目开发文档对应此分支。开始时工作区干净，本轮修改均保留本地，未提交、推送或部署。项目提供题库、比赛与判题，在此之上实现知识治理、题包导入、学习画像、RAG 和受控 Agent。容量以班级集中提交为主要场景；生产人数与 SLA 未定，不把本机功能测试当容量承诺。

## 依据、范围与方法

- 依据：[需求原件](../project/需求文档.docx)、[技术设计](../project/技术路线与功能实现设计.docx)、[项目计划](../project/大创项目计划书.md)、[当前完成矩阵](../plans/backend-completion-matrix.md)、工作 [OpenAPI](../openapi/) / [Schema](../schemas/)、运行文档和历史 H1–H7 证据。原始评审稿与历史报告未被覆写。
- 首先完整进行一轮只读审查和基线测试，然后按“越权及泄露 → 文件与事务安全 → 并发与任务恢复 → 超时及异常 → 综合回归”整改。独立模块并行审查，数据库测试串行执行。
- 追踪账号/Session、题目复制与下载、考试与比赛辅助、旧及新导入、提交与判题、学习/班级、知识审核、RAG/Agent、共享 API/限流、Nginx/worker 部署路径；通过真实 PostgreSQL/Redis 测试、并发反例、异常注入与本地 HTTP 服务核验高风险行为。
- 本轮实际使用隔离 Colima profile `xmuoj-merge-20261011`，测试库 `test_xmuoj_acceptance_20261012`；迁移另建并删除独立临时库。没有连接业务库、启动旧应用或使用真实学生数据。
- 首轮基线 **318 项 Django 测试，317 项通过、1 项 error**；错误为 ZIP 测试夹具时间戳使相同内容的包不再同 hash。初始 lint、工作契约、题包工具 6 项、部署 11 项通过。原始结果见[证据目录](backend-acceptance-evidence-2026-10-12/)。

## 首轮关键问题与整改结果

按阻断优先级分为以下 13 组。表中“已修复”表示本轮列明场景已修复并回归，不表示穷举了该模块所有输入。

| 编号 / 优先级 | 触发条件与后果 | 最小整改与证据 | 状态 |
| --- | --- | --- | --- |
| F01 / P1 权限边界 | 匿名指定用户名查询他人成绩/逐题状态；ACM 助手未按比赛管理权及 rank 所属比赛授权；删除他人 Session 时先删后校验。会泄露成绩或中断他人会话。 | 在对象范围内鉴权后读写；隐藏榜单规则一致；Session 删除先确认归属，注销当前 Session 使用 `logout`。[账号回归](../../backend/account/test_security.py)、[比赛回归](../../backend/contest/test_permissions.py)。 | 已修复 |
| F02 / P1 停用账号及并发写入 | 已停用管理员的旧 Session 继续进入管理路径；记录 Session 时保存整个旧 User 对象，可能覆盖并发修改的密码、停用状态或会话列表。 | 中间件使停用 Session 失效，权限层补检查；行锁合并 Session 列表且只保存该字段。[实现](../../backend/account/middleware.py)、[并发状态回归](../../backend/account/test_security.py)。 | 已修复 |
| F03 / P1 私密题目和比赛复制 | 管理员可复制他人隐藏/考试题、向他人比赛插题；重复复制及中途失败可能留下公开标志、部分行或共享目录。 | 校验源题、目标比赛及题目权限；事务锁和行锁串行复制，失败回滚数据库并只清理本次创建目录。[权限/并发/补偿回归](../../backend/problem/test_permissions.py)。 | 已修复 |
| F04 / P1 上传鉴权与同源文件 | 旧测试数据、ZIP/FPS 导入及富文本上传缺少 CSRF 或题目权限检查；伪图片可入库，上传 HTML 可作为同源主动内容被浏览器解释。 | 恢复权限/CSRF；相关前端每次上传读取新 CSRF token；使用 `ImageField` 检查图片；两套 Nginx 将非图片上传按二进制响应，添加 `nosniff` 和 `sandbox`；附件名按文本构造链接。[上传回归](../../backend/problem/test_import_security.py)、[共享回归](../../backend/utils/test_security_regressions.py)、[Nginx 实测](backend-acceptance-evidence-2026-10-12/nginx-results.json)。 | 已修复 |
| F05 / P1 测试文件误删及下载竞态 | 清理接口接受 `../` 等目录值，可删除根目录外内容或仍被题目使用的数据；多个下载写同一个 ZIP 可互相截断。隐藏比赛仍有下载入口。 | 限定目录 ID、拒绝符号链接和在用目录；隐藏比赛统一拒绝；每次下载使用独立临时文件并随响应关闭。[清理反例](../../backend/utils/test_security_regressions.py)、[下载并发回归](../../backend/problem/test_permissions.py)。 | 已修复 |
| F06 / P1 旧导入事务与资源上限 | `atomic` 内直接返回错误导致已导入题目提交；后续题目失败遗留测试文件/图片；ZIP 展开没有统一数量、体积与压缩比上限。 | 异常穿出事务后转 API 错误，失败补偿仅删除本次文件；复用既有导入限制和安全路径检查、有限读取。[ZIP/FPS 回归](../../backend/problem/test_import_security.py)。 | 已修复 |
| F07 / P1 判题消息丢失和永久占槽 | 初次发送失败时已经保存提交却给出错误；等待队列先取出再发送会丢任务；worker 硬退出留下 `task_number` 占用。普通与插件重试会放大问题。 | 增加 `JudgeDispatch` 持久投递记录，所有提交/重判入口同事务登记；提交后发送失败保留可恢复意图。PG 会话锁控制服务器槽位，失联释放，重复消息只结算一次；定时恢复孤儿任务。[服务](../../backend/judge/services.py)、[判题回归](../../backend/judge/tests.py)、[两个提交入口故障回归](../../backend/submission/tests.py)。 | 已修复；需迁移并同步部署恢复进程 |
| F08 / P1 敏感响应与日志 | 匿名榜单序列化整个 Profile，公开真实姓名/学校/专业及做题 JSON；共享 OI 提交携带 IP；旧异常日志记录原始异常/请求查询，可能带凭据或代码。 | 榜单字段白名单、共享提交不含 IP；通用错误仅记异常类型，不回显内部内容；提交查询失败返回明确错误，不伪装成功或放宽权限。[序列化](../../backend/account/serializers.py)、[提交](../../backend/submission/serializers.py)、[共享回归](../../backend/utils/test_security_regressions.py)。 | 已修复 |
| F09 / P2 限流并发 | 令牌桶非原子读改写；首轮确定性反例中一枚令牌被两个请求同时消费。高并发可绕过额度。 | 使用 Redis Lua 和 Redis 时钟原子补充、扣减及过期；八线程争抢一枚令牌仅一次成功。[实现](../../backend/utils/throttling.py)、[真实 Redis 回归](../../backend/utils/test_security_regressions.py)。 | 已修复 |
| F10 / P2 知识契约和审核竞态 | deprecated 知识点仍可改核心字段；审核队列选 ID 后若状态改变，hydrate 丢掉行导致 `KeyError` 500。 | deprecated 只允许 description/aliases，前端同步限制；hydrate 已选记录时不重新套可变状态条件。[服务](../../backend/knowledge/services.py)、[查询](../../backend/knowledge/queries.py)、[回归](../../backend/knowledge/tests.py)。 | 已修复 |
| F11 / P2 超时失效与失败吞没 | RAG 服务持续慢发响应头/正文可超过请求预算；缓存无 socket 超时；Dramatiq 的 URL 连接池覆盖平级 timeout 参数，实际仍无限等待；SMTP 无时限且异常被吞。 | HTTP 读取共享剩余预算；缓存、broker 和结果后端核验实际连接超时；SMTP 10 秒且有界重试。[RAG 回归](../../backend/rag/tests.py)、[共享回归](../../backend/utils/test_security_regressions.py)、[实际 Redis 加载回归](../../backend/utils/test_dramatiq_config.py)。 | 已修复；DNS 等系统调用的硬截止不作保证 |
| F12 / P2 空值和错误语义 | 旧 JSON API 接收 `null`/数组/标量后 `.get` 崩溃；插件分页对原始 offset 再次转换会 500。 | JSON 入口拒绝非对象及畸形/非 UTF-8 数据；分页使用已归一化结果 ID，不重复转换原输入。[API](../../backend/utils/api/api.py)、[插件](../../backend/plugin/views.py)、[边界回归](../../backend/utils/test_security_regressions.py)。 | 已修复 |
| F13 / P2 Agent 内部信息输出 | 输出过滤遗漏部分私网地址（如 172.16/12）和 Windows 等内部路径。模型响应可能将内部信息展示给学生。 | 按 IP 属性识别私网/回环/链路本地及内部主机名，补路径规则。[输出过滤](../../backend/agent_service/safety.py)、[反例回归](../../backend/agent_service/tests.py)。 | 已修复已列规则；完整答案防漏另见 D02 |

另修正一项验收基础问题：ZIP 夹具使用固定 `ZipInfo` 时间戳，避免同内容重复上传测试因 ZIP 元数据随机失败。没有改变生产包的 hash 或冲突语义。

## 七类重点核查的实际边界

| 维度 | 本轮覆盖 | 仍不能据此宣称 |
| --- | --- | --- |
| 空值 | 旧 API 的 JSON 根类型、畸形请求，新模块既有 null/标识符/Schema 回归，旧上传异常题目 | 穷举每个旧管理接口的所有组合输入 |
| 重复请求 | 导入/Agent 既有幂等，判题重复消息、丢失发送恢复、重复复制、学习 revision 与回放 | 所有创建提交的 HTTP POST 都幂等；新提交按原契约仍是新 attempt，未添加请求幂等键 |
| 并发 | 权限对象隔离、Session 合并、复制事务、下载临时文件、Redis 令牌桶、判题会话锁/槽位、知识审核读取 | 已达到目标班级容量；外部 Judge 恰好执行一次 |
| 权限 | 匿名/学生/管理员 OWN/无权限/Super Admin/停用账号/他人比赛和 Session/隐藏榜单及 CSRF | VSCode 插件现有 token 登录协议已闭合 |
| 超时 | HTTP 慢头和慢体、Redis 实际连接选项、SMTP 有界重试、既有 Agent/导入恢复 | 操作系统 DNS、所有多地址连接/TLS 阶段都能被同步标准库严格按同一墙钟强制中断 |
| 异常 | 数据库回滚、文件补偿、投递失败持久化、明确失败有界重试、错误 envelope、通用日志 | 任意异常均自动恢复；确定失败仍需要排障后显式恢复 |
| 敏感信息 | 返回字段最小化、IP、原始异常/请求、内网地址与路径、上传主动内容 | 任意模型输出绝不含完整答案，或已经对全部历史数据完成清洗 |

## 实际验证结果

以下为本轮最后有效结果，失败历史另存，不以历史通过替代本次结果。

| 检查及实际入口 | 结果 | 原始证据 |
| --- | --- | --- |
| 后端 `python manage.py test --settings=oj.settings --noinput` | **379 项全部通过，46.204 秒，退出码 0**；较首轮增加 61 项 | [完整日志](backend-acceptance-evidence-2026-10-12/test-final-fixed.log)、[进程结果](backend-acceptance-evidence-2026-10-12/test-final-fixed-result.json) |
| 后端 `flake8 --statistics .` | 通过，无输出 | [日志](backend-acceptance-evidence-2026-10-12/backend-lint.log) |
| 独立空库 `migrate --noinput`、`makemigrations --check --dry-run`、`check`、`migrate --plan` | 全部退出码 0；包含 judge 新表；无模型漂移、无系统问题、无待执行迁移；临时库已删除 | [结果](backend-acceptance-evidence-2026-10-12/migration-results.json)、[迁移日志](backend-acceptance-evidence-2026-10-12/fresh-migrate.log) |
| Node 24：`npm test` | **21 文件、96 项全部通过** | [日志](backend-acceptance-evidence-2026-10-12/frontend-tests.log) |
| Node 24：`npm run lint`、`npm run build` | 两者退出码 0；构建有既有 chunk 大小警告，未改打包策略 | [lint](backend-acceptance-evidence-2026-10-12/frontend-lint.log)、[build](backend-acceptance-evidence-2026-10-12/frontend-build.log) |
| `python tools/problem_batch/validate_contracts.py` | 工作契约和黄金数据校验通过 | [日志](backend-acceptance-evidence-2026-10-12/contracts.log) |
| `python -m unittest discover -s tools/problem_batch/tests -v` | 6 项通过 | [日志](backend-acceptance-evidence-2026-10-12/problem-batch-tools.log) |
| `python -m unittest discover -s backend/deploy -p 'test_*.py' -v` | 11 项通过 | [日志](backend-acceptance-evidence-2026-10-12/deploy-tests.log) |
| nginx:alpine 临时容器加载两套配置 | **2 次语法检查＋4 次 HTTP 检查通过**；HTML 为 octet-stream，PNG 为 image/png，均有 nosniff/sandbox；容器已移除 | [结果](backend-acceptance-evidence-2026-10-12/nginx-results.json)、[实测脚本](backend-acceptance-evidence-2026-10-12/check_nginx.py) |
| 独立只读复核 | 判题遗漏的插件投递入口已补齐；RAG 慢响应头预算已补齐，均有回归；其他指定改动未发现第二个已证实阻断 | 本报告 F07/F11，最终全库包含对应反例 |

过程中保留了失败证据：首次基线 ZIP 夹具错误；首次权限定向测试的流式响应关闭与测试数据库 teardown 冲突（纯文件测试改为 `SimpleTestCase`）；第一次整改后全量 378 项中的两个旧断言——合法带引号的下载文件名、停用账号提前被中间件拦截而不再进入原同步屏障。调整测试时保留了下载内容及并发权限断言，没有为了通过而放开实现权限。

本轮判题结果使用受控 Judge 响应替身；协议测试使用真实本机 HTTP 服务；Agent/导入的既有真实 Redis worker 回归包含在全库测试中。**没有重新运行真实 JudgeServer、真实模型/Embedding/Milvus、生产 TLS、全量生产镜像或容量压测。** 历史 H7 成功证据不替代本轮改变后的运行验收。

## 新判题机制的交付要求

1. 新增 `judge.0001_initial`，部署时先迁移再运行新代码，并配置 `recover_workflows judge --interval 30`。自定义部署需要同步 Supervisor 与恢复命令。
2. 升级应停止旧 web/worker 的写入并等待旧判题结束，再切换新 worker；不要让按旧 `task_number` 分配的 worker 与新会话锁机制混跑。本轮没有执行生产切换。
3. 数据库必须保留 PostgreSQL 会话锁语义，不能使用 transaction pooling。`task_number` 现在只展示实际占用投影，不参与分配；连接死亡释放锁，失锁 worker 不发布迟到结果。
4. 升级前的 PENDING 和待重判记录可回填；旧 JUDGING 不盲目重判。定位故障后用 `recover_judge <submission_id>` 恢复；failed 不在后台无限重试。
5. 外部 Judge 调用是至少一次：调用方失联时远端可能仍在计算。数据库结果应用通过锁和事务防重，不能据此声称远端程序只执行一次。比赛的历史计分规则没有更改。

## 人工待决与尚未交付（已跳过实施）

| 编号 | 事实与影响 | 建议下一步；需要用户给出的决定 |
| --- | --- | --- |
| D01 比赛重判计分 | 原计数累加逻辑在 AC→WA、重复 WA 重判等情形不能完整回退；结束后重判的排名处理、ACM 首 AC/罚时、OI 最高分/最后分口径未明确。普通练习题既有重算不等于比赛已解决。 | 优先明确规则后按比赛全部有效提交重建排名；建议 ACM 以首个 AC 及其之前罚时、OI 最高有效分、赛后重判更新审计可追踪排名。确认是否采用，及历史比赛处理范围。 |
| D02 AI 完整答案防漏 | 首轮反例：顶层 Python A+B 程序配合 `contains_full_solution=false` 可通过现有 Schema/输出过滤。模型自报布尔值不是可信保证，正则也无法判定任意代码是否为完整答案。 | 明确允许的教学片段和误拦容忍度；建议先采用提示/伪代码优先的严格策略，复杂输出增加审核或二次判定，再独立做对抗验收。未擅自全面禁止教学代码。 |
| D03 依赖安全升级 | 当前锁定 Django 3.2.25 与 Gunicorn 21.2.0。Django 官方已宣布 3.2 结束扩展支持；Gunicorn 22.0.0 官方发布记录包含 HTTP 解析/request smuggling 安全修复。 | 发布前迁移到仍受支持的 Django 版本和安全版 Gunicorn，并验证中间件/DRF/JSONField/部署兼容；需要确定升级窗口和兼容范围。不是只改 requirements 版本号。 |
| D04 插件鉴权 | `PluginLoginAPI` 返回 `auth_token` 但不创建 Session；token 存在 SSO 身份查询用途，插件请求中间件只接 APPKEY，没有消费此 token。外部 VSCode 客户端不在仓库。 | 先确认客户端 Cookie/CSRF 能力，优先复用 Session；否则设计独立有期限、可撤销的插件 token。不要把现有 SSO token 直接扩成全站 Bearer 权限。 |
| D05 功能范围 | 当前工作契约是学习 6＋Agent 4＋导入 5＋知识 21＝36 HTTP 操作。原始需求中的教师高频错题/错误类型/难度偏差/AI 效果分析与教学开关尚未完整实现；近期复盘为 Mock/Proposed contract；跨平台采集、跨来源相似检测和质量规则不属于现有来源键/hash 导入去重。 | 确定这些功能是否纳入当前交付及先后顺序；另定教师权限/开关粒度、复盘时间窗口与生成预算、采集来源/相似阈值/审核负责人。知识审核当前仅 Super Admin，不擅自扩大教师全站权限。 |
| D06 真实环境与内容 | 缺真实模型/Embedding/Milvus 配置、前 20 道高频题审核资料和教学班输入。历史 H1 的 60/120/240 人最终一致性通过，但建议延迟阈值均未通过，且为 QEMU 本机数据。生产域名/TLS 拓扑及数据与文件一致性恢复未验收。 | 提供负责人、非公开配置注入方式、目标硬件/班级规模/响应 SLA；在目标环境复验判题新机制、容量、完整备份恢复和真实依赖。跨团队签字仍按既有约定暂缓，不拿签字替代技术验证。 |

D03 官方依据：[Django 3.2 EOL 公告](https://www.djangoproject.com/weblog/2024/apr/03/bugfix-release/)、[Gunicorn 22.0.0 安全修复说明](https://github.com/benoitc/gunicorn/releases/tag/22.0.0)。本轮只核验这些已知直接依赖，未声称做了完整依赖漏洞数据库扫描。

建议后续顺序：先 D01/D02/D03 的发布阻断，再 D04 的插件协议；D05 按交付范围排期，D06 的配置和真实内容可以同时准备。对应决定未收到前，本轮不自动实施这些策略或对外发布。
