# 后端开发与运行

当前分支为 `duduking19`，以组织远端 `144410a` 为代码基线。旧工作库及未提交修改完整留在上级 `资料归档/2026-10-07/旧本地仓库`。原始交付文件没有被覆盖；开发采用工作契约及明确记录的修订，未代签冻结文件。

2026-10-11 在此本地后端基础上合入 `origin/shiyuan@6d969e6` 的 Vue 3/Vite 前端，并适配本地 API。知识模型、迁移、权限和学习/Agent 服务继续使用本地实现；合并范围与本轮验证见 [合并记录](reviews/local-first-merge-2026-10-11.md)。前端现在使用 Node 24、`npm ci` 和 `npm run build`，以下旧验收记录中的 Webpack/DLL 命令仅用于解释历史证据。

## 环境与启动

当前依赖为 Django 5.2.18 LTS、DRF 3.18.3、Gunicorn 26.2.0，要求 Python 3.10+、PostgreSQL 14+。本机验收组合为 Python 3.11.15、PostgreSQL 14、Redis 7，镜像采用 Python 3.12 Alpine。升级后须在所用虚拟环境重新安装 `backend/deploy/requirements.txt`；项目根 `.venv` 可能仍保留旧版依赖，本轮使用独立临时环境，没有覆盖它。契约测试额外需要 `tools/problem_batch/requirements-contract.txt`；无 pip 的 uv 环境可使用 `uv pip install --python .venv/bin/python -r ...`。

隔离测试容器使用 Docker context `colima-xmuoj`：

- PostgreSQL：`127.0.0.1:15432`，测试数据库 `onlinejudge`；专用数据库用于并行模块和性能验证。
- Redis：`127.0.0.1:16379`。
- 容器名 `xmuoj-ai-test-postgres-20261007`、`xmuoj-ai-test-redis-20261007`；数据库存储为临时测试空间，不承诺停容器后的持久化。不要在此环境录入真实业务数据。
- 旧服务仍占用本机 8000，因此新代码开发服务使用 8001。

从 `backend/` 执行：

```sh
export POSTGRES_PORT=15432 REDIS_PORT=16379
../.venv/bin/python manage.py migrate --settings=oj.settings
# 空开发库：先在当前 shell 设置 DJANGO_SUPERUSER_PASSWORD，再初始化管理员
../.venv/bin/python manage.py inituser --action=bootstrap --settings=oj.settings
../.venv/bin/python manage.py runserver 127.0.0.1:8001 --settings=oj.settings
# 另开进程：
../.venv/bin/python manage.py rundramatiq --settings=oj.settings
```

新 API 均使用真实 Django Session，不接受 APPKEY 替代登录；写入需 CSRF。知识点 API 响应版本 0.9.9，导入/学习/Agent 为 1.0.0。

## 数据与配置入口

1. **知识体系**：知识管理员通过 `/api/admin/knowledge-points` 创建草稿、发布知识点；依赖和题目标注采用两人审批，禁止提交人自审。正式映射只存 approved 数据。
2. **题库导入**：使用 `problem_import` 五个 API 或 `import_collected_problems` 管理命令。正式 ZIP、Manifest、JSONL、CSV、测试点和转换产物必须通过一致性校验，警告须显式确认。旧包中的字符串 `knowledge_candidates` 缺少 role/weight，仅保留待补充候选并给出警告，绝不直接写正式标注。详见工作导入契约及模块 README。
3. **班级与学习**：通过 `sync_teaching_class` 合并明确审核的名册；学习评分随普通题判题终态更新，也可使用 `recover_learning --backfill --sync` 补历史提交。详见 [实施说明](learning-implementation-2026-10-07.md)。
4. **RAG**：`ingest_rag` 录入经审核的文本与元数据；`rebuild_rag_index` 建索引。默认真实 PostgreSQL 检索，可配置真实 Embedding/Milvus HTTP 服务。见 [RAG 说明](../backend/rag/README.md)。
5. **Agent**：配置 `AGENT_MODEL_URL`、`AGENT_MODEL_NAME` 和必要的 `AGENT_MODEL_API_KEY`，并维护 `AGENT_MODEL_CONFIG_VERSION`。支持四种服务、17个工具名/18种服务签名，服务端控制范围、次数、时间、提示等级和输出 Schema。未配置供应商明确返回503；没有内置伪成功回答。见 [Agent 说明](../backend/agent_service/README.md)。

首次容器启动空库时必须设置 `DJANGO_SUPERUSER_PASSWORD`，可选 `DJANGO_SUPERUSER_USERNAME`（默认 root）；已有超级管理员时跳过初始化，不修改其密码。迁移连续失败5次将退出，不启动服务。Sentry 只有在生产环境显式设置 `SENTRY_DSN` 后才启用；已替换归档的 Raven SDK，仅发送白名单事件元数据与异常类型，不发送请求、代码、凭据、局部变量或原始异常文本。

部署凭据通过环境变量注入，不放入仓库、请求参数或日志。外部模型、Embedding、Milvus 与真实教学语料需要部署方提供；本地协议夹具验证不等同于这些服务已联通。

初轮 Python 3.12 Alpine 隔离验证使用旧镜像补依赖/复制源码，实际启动、权限与任务恢复通过；本机ARM运行旧x86镜像时，审查容器用 `GUNICORN_CMD_ARGS="--timeout 180"` 临时覆盖默认30秒冷启动预算。该阶段并非从零构建，生产默认未修改，历史记录见[初轮部署验收](reviews/backend-evidence-2026-10-07/deploy/backend-deployment-acceptance.md)。

本轮H1–H7已完成[前端生产构建](reviews/backend-h1-h7-evidence-2026-10-07/build/frontend-build.txt)及[从零完整镜像构建](reviews/backend-h1-h7-evidence-2026-10-07/build/image-clean-build.txt)。首次运行的[10项TLS/账号基础链路及Judge失败](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/first-failure-runtime-results.json)保留为历史证据。心跳竞态修复后，最终镜像[20项真实运行检查](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/runtime-results.json)和[7项可信代理检查](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/proxy-results.json)全部通过：包含真实Judge AC→队列画像→幂等重判、离线排队→重启恢复→画像→推荐，以及凭据权限、重试与后台到期清理。模型未配置返回明确503，不是外部模型联通证明。[270个生产文件比对](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/image-source-check.json)全部一致。本轮三个H7应用容器已停止，卷和镜像保留，旧应用未改动。生产域名、证书及TLS终止拓扑尚未提供；安全模式与可信代理边界见[HTTPS部署说明](deployment-https.md)。

## 任务恢复与权限

新任务保存数据库状态后再投递队列。生产 Supervisor 配置已加入学习、Agent、导入和判题四个独立恢复进程，各自每30秒扫描；Web 与 worker 统一使用 `server` 用户，保证 worker 能读取权限为700的私有题包目录与写入测试目录。升级既有自定义部署时也要对齐服务用户与共享卷权限。

在非 Supervisor 开发环境分别运行：

```sh
python manage.py recover_workflows learning --interval 30
python manage.py recover_workflows agent --interval 30
python manage.py recover_workflows import --interval 30
python manage.py recover_workflows judge --interval 30
```

不带 interval 时只执行一轮。Import 内部仍按过期时限和活跃 worker 锁判断，不抢占正常进行的批次。Agent 将超时的 running 标记失败并回投丢失的 queued 任务；Learning 可从提交记录补齐遗漏事件并按 revision 幂等回放：新补采事件立即投递，已存在未完成事件闲置超过5分钟才异步补投，避免每30秒扫描都向队列重复发送；`--sync`仍立即处理，worker保持幂等。

Judge 从 `JudgeDispatch` 重发未领取消息、恢复无活跃会话锁的中断 worker，并同步判题服务器占用数；明确失败的任务不会被恢复器无限重试。修复其故障后运行 `recover_judge <submission_id>` 显式恢复 JUDGING。外部 Judge 的网络执行是至少一次，普通题终态与计分通过提交锁和数据库事务避免重复应用；连接池必须保留 PostgreSQL 会话锁语义。详见[学习与判题恢复边界](learning-implementation-2026-10-07.md)。

比赛计分采用 ACM 首次 AC 与此前每次错误20分钟罚时（CE、系统错误及等待状态不罚时），OI 每题最高有效分；赛后重判按原提交时间更新。升级后需对历史受影响比赛执行 `python manage.py rebuild_contest_scores <contest_id>`，身份变化或删除记录后也使用该命令重建；它只修改该场比赛的派生成绩，不会重判或改写原提交。具体有效身份、时窗、状态、缓存和校准规则见[比赛计分说明](learning-implementation-2026-10-07.md)。

## 迁移与兼容

- 补齐既有 Contest.is_exam 的迁移和 JSONField 模型状态；修正旧 submission.0007 的外键迁移依赖顺序，使空库安装不依赖偶然的 app 排序。
- 普通题 `_id` 增加 `contest IS NULL` 条件唯一约束。升级库若已有重复题号，迁移会明确失败，需先人工决定如何合并/更名；不会自动删除或改绑历史数据。
- 有知识审批、学习、导入历史引用的题目/用户不能直接物理删除；旧入口返回明确 `resource-in-use`，保留历史。应隐藏题目、禁用用户或归档班级。
- 重判入口改为 POST，并同步既有前端调用；重复 delivery、AC撤回和OI分数变化通过针对性回归。比赛现按上文确定的规则重建派生成绩，历史修复需显式运行重建命令。

初轮迁移回退已在独立数据库副本执行：13条逆迁移后重新升级，撤销初始迁移会删除30张新增表及数据。该证据不覆盖后来新增的 `account.0014_user_credential_export`、`rag.0002_lexical_search_indexes` 及 `conf.0005_judgeserver_hostname_unique`。account/rag正向建库由本轮312项阶段回归及[H5索引迁移日志](reviews/backend-h1-h7-evidence-2026-10-07/h5/rag/migrate-indexes.txt)覆盖；conf.0005随后通过[23项conf回归](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/heartbeat-after.txt)及[2项强化迁移边界](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/heartbeat-migration-boundaries.txt)，包含空闲重复合并与非零任务计数时拒绝迁移；[新镜像启动](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/final-container-startup.txt)已自动应用该迁移并处理原重复记录，[心跳汇总](reviews/backend-h1-h7-evidence-2026-10-07/h6-h7/heartbeat-runtime-summary.json)确认1条且task_number=0。三者均不能直接沿用初轮逆迁移通过结论；新增account/rag/conf的完整数据恢复仍未演练。

生产升级前需数据库、测试文件、私有导入归档、凭据导出文件及配置的一致性备份；不能用降级后重新 migrate 代替数据恢复。见[初轮回退演练与恢复策略](reviews/backend-evidence-2026-10-07/migration-rollback-strategy.md)；真实生产数据与配套文件一致性恢复尚未验收。

## 验证

已有结果按阶段保存：初轮全库270项、Claude整改后271项；本轮H1–H5及知识排序补例后的[全库312项](reviews/backend-h1-h7-evidence-2026-10-07/backend-full-tests.txt)通过（375.492秒）。312项早于Judge心跳修复和conf.0005；修复后的[最终全库317项](reviews/backend-h1-h7-evidence-2026-10-07/backend-final-317-tests.txt)已通过（686.417秒，退出码0），最终镜像真实链路结果如上。完整范围及限制见[本轮验收记录](reviews/backend-h1-h7-acceptance-2026-10-07.md)；以下为可复现命令，不是再次执行的声明。

```sh
# backend 目录
POSTGRES_PORT=15432 REDIS_PORT=16379 ../.venv/bin/python manage.py test --settings=oj.settings --noinput
../.venv/bin/flake8 --statistics .
POSTGRES_PORT=15432 REDIS_PORT=16379 ../.venv/bin/python manage.py makemigrations --check --dry-run --settings=oj.settings
# 仓库根目录
.venv/bin/python tools/problem_batch/validate_contracts.py
.venv/bin/python -m unittest discover -s tools/problem_batch/tests
```

`tools/benchmark_knowledge.py` 只允许写入名字以 `xmuoj_benchmark` 开头的空测试库，构造10万映射后测列表、审核队列、审批及深度3图查询。对已构造且规模一致的专用库可传 `--reuse` 再测；审批测试会消耗28条待审批次。其本机顺序请求结果不替代真实部署、多用户负载及公网网络验收。[H1的60/120/240人测量](reviews/backend-h1-h7-evidence-2026-10-07/h1/README.md)已完成：最终一致性通过，但突发至落库P95为60.331/118.348/276.825秒，三档容量建议阈值均未通过。实验采用本机QEMU PostgreSQL与私有队列，未包含真实Dramatiq传输、Judge执行、HTTP或生产网络。容量缺口、目标硬件SLA及真实外部服务仍需验收，不能由退出码0或数据库最终一致推断通过。实际结果按阶段登记在[完成矩阵](plans/backend-completion-matrix.md)与[本轮验收报告](reviews/backend-h1-h7-acceptance-2026-10-07.md)。
