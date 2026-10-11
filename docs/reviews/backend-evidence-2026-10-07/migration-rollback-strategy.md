# 迁移回退演练与备份策略（2026-10-07）

本次演练通过。范围仅为隔离 PostgreSQL 14.23 容器 `xmuoj-ai-test-postgres-20261007`（127.0.0.1:15432）中新建的 `xmuoj_rollback`；源库为该容器内已迁移的 `onlinejudge`。没有删除既有数据库，也没有对源库或其他测试库执行写入。源库 User/Problem 均为0行；演练前后源库迁移清单及两者行数一致。

## 已执行结果

| 检查 | 实际结果与边界 |
| --- | --- |
| 自定义格式备份与恢复 | `pg_dump --format=custom --no-owner --no-acl` → 新建 `xmuoj_rollback` → `pg_restore --exit-on-error` 成功。备份246668字节，路径和SHA-256见结果JSON；备份存本机临时目录，未将数据库归档提交到仓库 |
| 反向依赖计划 | MigrationExecutor 在副本上计算并执行13条反向迁移；退出 knowledge/learning/agent_service/rag/problem_import 五个新增app，并返回 account0012、problem0015、submission0012、contest0012、options0003。完整节点和操作见计划 |
| 有数据的学习字段往返 | 副本插入1条 ProblemKnowledgeRating：attempt_count=7、accepted_count=3、rating=1234.5678、confidence=0.750。learning0002→0001将列改回sample_count，再升0002后四个值一致；这是代表行验证，非全数据无损证明 |
| 新模块整体回退 | 30张新增表全部消失，知识历史触发器消失。这一步明确删除副本中的新增模块行，包括上面的测试rating；旧表中的测试User/Problem保留 |
| 重升当前全部叶子 | 30张表和3个知识历史触发器恢复，迁移计划为空。旧User.session_keys和Problem.samples两个JSON样本保持一致；已删除的新模块rating没有恢复，证明“重升”不是数据恢复 |
| 历史保护 | 回退前、重升后各插入副本测试事件，原始SQL UPDATE均被知识触发器以SQLSTATE 23514拒绝；事件内容保持不变 |
| 当前代码兼容检查 | `check` 无问题；`makemigrations --check --dry-run` 输出 `No changes detected` |
| 连接释放 | 所有Django连接已关闭，独立查询确认 `clone_connections=0`；副本保留供检查，未删除 |

[原始建库/恢复输出](migration-rollback-clone-plan.txt)、[反向依赖计划](migration-rollback-plan.txt)、[执行输出](migration-rollback-exercise.txt)、[结构化结果](migration-rollback-results.json)、[连接检查](migration-rollback-connections.txt)、[完整脚本](migration_rollback_probe.py)。计划中 operations 是 Django 迁移的正向描述；`backwards: true` 表示执行其逆操作，例如 CreateModel 的逆操作是删除表。

## 不能据此承诺的回退能力

- `knowledge 0002 → 0001` 的真实计划会先反向执行 problem_import0001、learning0002/0001、agent_service0001；这些app依赖knowledge0002。因此这条命令会删除相关业务表，绝非只移除三个触发器。不得直接用于有数据的生产库。
- 完整回退会删除知识审核、学习/班级/事件、RAG、Agent及导入记录。contest0013的逆操作还会删除is_exam列；problem0017的逆操作移除普通题展示编号唯一约束。在此窗口接受重复数据，会阻止重新建立约束。重升只重建结构，不恢复丢失记录。
- 本次没有验证生产数据规模、在线写入中的回退、跨服务备份一致性、测试文件或导入归档恢复、Milvus索引/真实外部服务恢复，也没有测量生产RTO/RPO。源库既有数据很少，不能据此承诺生产迁移时长。
- learning0002还改变TeachingClass.term长度和默认状态。样例验证仅证明计数字段改名及代表行保存；若在旧状态写入长度33～64的term，再升0002会有缩短列风险，应先检查 `SELECT id FROM teaching_class WHERE length(term)>32`。应用代码与字段名称必须匹配，不能用本演练替代旧应用版本兼容测试。

## 可执行的备份与恢复选择

1. 发布前暂停业务写入、队列worker及所有周期恢复进程，记录应用镜像/代码版本、迁移叶子、配置版本和备份时刻。在同一静止窗口备份数据库以及测试数据目录、导入原始包/分配目录和其他不可重建文件。数据库备份独立于外部向量索引；后者应记录模型/集合版本，并保留可重建的PostgreSQL资料来源。
2. 使用受限权限连接执行 `pg_dump --format=custom --no-owner --no-acl`，保存SHA-256与备份清单，`pg_restore --list` 检查归档，再恢复到全新数据库验证。不要使用 `--clean` 指向现有业务库。本文脚本中的两阶段流程就是已实跑的隔离版本；完整数据备份应由部署环境的备份管理保管，临时目录副本不充当长期备份。
3. 若只需撤销应用发布，优先考虑经过兼容验证的旧应用版本或向前修复。不能假设数据库增加表就与所有旧版本兼容；字段改名、唯一约束及任务消费者均要对齐。每次真实操作前重新运行 `manage.py migrate <app> <target> --plan` 并检查跨app逆依赖。
4. 确需恢复到发布前数据时，从对应时刻的完整备份恢复到**新库**，恢复同一时刻的文件和匹配的应用版本，在隔离环境验证迁移状态、权限、样例判题和任务恢复，再切换连接并开放写入。记录备份之后数据的丢失窗口；需要保留新增写入时，应先设计并验证增量恢复/PITR或业务重放，不能执行完整逆迁移后指望重升自动找回。
5. 只有经审查确认不会触及不可恢复数据的局部迁移，才按审定计划逆迁移。针对本次learning0002的局部方案，先检查实际计划仅含该条、term数据满足重新升版约束、应用版本匹配；其他条件不满足时保留现有数据并向前修复。

## 本次演练命令

以下命令已执行，仅限本仓库和上面明确的隔离容器。脚本默认目标固定为xmuoj_rollback，发现目标库或已有结果文件就拒绝重新创建，不自动drop/reuse；这不是可直接用于生产库的部署脚本。

```sh
.venv/bin/python docs/reviews/backend-evidence-2026-10-07/migration_rollback_probe.py clone-plan
# 读取 migration-rollback-plan.txt，确认固定副本及逆依赖范围。
.venv/bin/python docs/reviews/backend-evidence-2026-10-07/migration_rollback_probe.py exercise
```

重复演练应选择新的专用副本名及独立证据目录，并据此复核保护常量；不要为复跑删除本次库或覆盖原始证据。
