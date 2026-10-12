> 历史记录：本文保留H1–H7授权实施前的初轮验收状态及原文，34项HTTP、271项回归和七项待人工决策均为当时记录。用户随后已授权整改；当前结果及未完成项以[H1–H7验收报告](backend-h1-h7-acceptance-2026-10-07.md)和[当前任务清单](../plans/backend-follow-up-2026-10-07.md)为准。

# 后端实现与验收记录（2026-10-07）

状态：本轮后端实现与自身验收完成；**Claude Opus 5.5 High 独立验收有条件通过**，三个明确缺陷已修复，整改后271项Django全库回归通过。七项人工决策按用户要求跳过自动修改，生产及外部联调边界见下文。

## 实现范围

在 `duduking19`、组织仓库 `144410a5a1847afa443f6ee609e13fdc256e187d` 基线上实现知识管理与双人审批、题包导入、教学班授权、学习画像与推荐、RAG、四类受控 Agent；新增 34 个 HTTP 操作、17 个工具名/18 个服务签名。模型与接口逐项证据见 [完成矩阵](../plans/backend-completion-matrix.md)。

共用真实 Session/CSRF、版本及 request_id、输入校验与错误脱敏。涉及已有代码的功能修订包括：判题重复消费/重判后的普通题统计、重判改 POST、历史引用删除保护，以及全批用户导入事务与旧用户资料保护。运行说明见 [backend-development.md](../backend-development.md)。

## 本轮发现并修复

- 工作契约的 null、审核 discriminator、历史快照及只读查询缺口已在工作副本修订；原交付包原样保留，不代签冻结记录。
- 真实空库迁移暴露旧外键迁移顺序问题，补齐依赖及现有模型状态。普通题展示编号增加条件唯一约束；旧数据冲突明确报错，不擅自合并。
- 重复请求/worker、并发图审核、映射版本竞争、学习事件补采、重判重放、资料失效与权限变化都有针对性回归。
- 用户导入修复前的三个反例均失败；修复后同一测试组通过。证据为本目录 `backend-evidence-2026-10-07/xmuoj-account-import-before.txt`、`xmuoj-account-import-after.txt`。
- 生产启动改为迁移失败即退出，首次管理员密码从环境注入，已有管理员保持不变；队列及恢复进程使用可访问私有题包的服务用户。历史上游 Sentry DSN 已移除，仅显式配置才启用。
- 十万条映射的初次压测发现管理列表计数重复扫描全表，P95 10069ms；已按当前页一次汇总计数；同一10万映射库停止并行测试后复测P95 **192.98ms**，满足本机500ms目标。[最终结果](backend-evidence-2026-10-07/knowledge-benchmark-final.json)同时记录审核队列68.54ms、图查询91.26ms、映射审批231.99ms；最初失败及混合负载结果均保留。

## 验证记录

- Python 3.11 编译、全后端 flake8、Django check、makemigrations --check --dry-run 通过；隔离 PostgreSQL 14 完成全部迁移。
- 三个 recover_workflows 单轮命令实际执行成功；本机 8001 真实 HTTP 的五个新接口入口均返回预期 401、JSON、版本头及 request_id。
- 全部工作 OpenAPI/JSON Schema 及黄金题包校验通过；题包构建器 6 项单测通过。
- 修复后完整 Django 回归 **270项通过，605.750秒，退出码0**；原始日志为 [full-backend-tests.txt](backend-evidence-2026-10-07/full-backend-tests.txt)。第一次失败与中途停止的73项不计作全库通过。
- 专用数据库副本完成13条逆迁移及重新升级：30张新增表可撤销/重建，learning计数字段的有数据往返保持，历史保护触发器重升后仍有效。全量回退会删除新模块数据，[恢复策略与证据](backend-evidence-2026-10-07/migration-rollback-strategy.md)明确限定于该副本；未进行生产无损恢复演练。
- 新增健康检查8项单测通过。Python3.12 Alpine隔离审查容器完成4项bootstrap真实PG测试、六进程启动、权限检查、HTTP健康由1转0以及真实学习事件自动补采/消费。旧x86镜像在ARM/QEMU下仅该审查容器使用180秒Gunicorn冷启动预算；生产默认30秒不变。主审查容器已停止保留，专用临时Redis已停止。未从零构建生产镜像。[部署完整证据](backend-evidence-2026-10-07/deploy/backend-deployment-acceptance.md)。
- 已在本机Claude Code「大创」工作区，以UI显示的 **Opus 5.5 / High** 原文发送用户提示。Claude独立重跑基线270项，通过后修复3项缺陷并完成 **271项全库回归（263.285s，退出码0）**。完整[独立报告](claude-backend-acceptance-2026-10-07.md)与[会话记录](backend-evidence-2026-10-07/claude-review-session.json)已保存；Mac锁屏后通过项目内完成的书面报告取得最终结论，未绕过锁屏。

## 验证范围与外部条件

PostgreSQL 并发、Redis 队列、Django API 与恢复逻辑已在隔离环境验证。模型、Embedding、Milvus 的外部调用测试采用本地真实 HTTP 协议夹具；JudgeServer RPC 使用测试替身。尚未验证实际供应商、真实评测沙箱、生产数据升级、教师试点效果或公网多用户负载。

十万映射基准为本机顺序请求（Django HTTP 栈、PostgreSQL、Redis），不代表生产网络与并发 SLA。仅同步了重判请求的既有前端调用，未实现新的 Vue 页面；前端 node_modules/dist 缺失时，不能声称前端完整构建或完整新镜像已通过。

没有创建提交、推送分支、合并或生产发布。旧本地库与未提交内容继续保留于上级资料归档；当前功能改动保持未提交，方便审核。

二次验收前已保存代码与文档快照至上级 `资料归档/2026-10-07/Claude二次验收前开发快照/`，归档内568个文件逐个核对SHA-256；该目录另含manifest与Git二进制补丁，未创建提交。

## 二次验收修订与人工决策

Claude修复了：无题目权限的Admin仍可访问导入；恢复进程每30秒重复投递全部未完成学习事件；Nginx的200 MiB限制挡住契约允许的256 MiB题包。对应代码/回归均列在独立报告中；root对这些修订做了代码核对、定向lint/编译与diff检查。

验收结论是有条件通过，没有剩余自动可处理阻断。H1–H7涉及全局锁/班级并发、导入批次归属、中文审计头编码、批量账户默认密码、分页/RAG索引规模、生产HTTPS配置及真实外部依赖。它们需要业务或部署决策，未擅自修改，见[当前任务清单](../plans/backend-follow-up-2026-10-07.md)。学习重投节流旨在减少队列重复消息，worker仍需保持幂等；不宣称消息系统恰好一次投递。
