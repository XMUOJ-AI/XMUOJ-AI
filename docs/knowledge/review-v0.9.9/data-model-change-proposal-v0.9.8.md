# XMUOJ 知识点体系模块数据模型变更提案

- 提案版本：0.9.8
- 提案日期：2026-09-17
- 状态：待上游数据模型负责人批准
- 目标文件：`docs/data-model-v1.md` 第 5 节及对应迁移规范

## 1 结论

知识点模块不能直接按当前冻结数据模型实施。当前模型与已确认产品规则存在四项冲突，并缺少三个审核与历史对象。建议按本提案修改上游模型后，再冻结知识点模块 1.0.0。提案未合入前，任何 Agent 都不得创建模型或迁移。

## 2 冲突和修改

| 编号 | 当前冻结模型 | 已确认产品规则 | 建议修改 |
|---|---|---|---|
| DM-01 | KnowledgePoint 默认 active | API 新建知识点先保存为 draft | API 创建默认 draft；导入工具只有在显式审核后可写 active |
| DM-02 | KnowledgeDependency 唯一键含 relation_type | 同一有向点对只能有一条边 | 唯一键改为 prerequisite_id 与 dependent_id |
| DM-03 | KnowledgeDependency 没有 version | update/delete 申请需要乐观锁 | 增加 version，初始 1，批准 update 后加 1 |
| DM-04 | 每个已发布题必须有 approved primary | 历史题允许 unannotated，不阻断发布和判题 | 约束只作用于“存在当前映射集合”的题目；无集合时派生 unannotated |

## 3 新增对象

### 3.1 KnowledgeDependencyChangeRequest

所有依赖 create、update、delete 都先写入变更申请。正式 KnowledgeDependency 只保存当前生效边，申请批准前不改变正式边。

必需字段：UUID id、operation、target_dependency_id、base_version、拟提交的 prerequisite_id、dependent_id、relation_type、weight、status、reason、review_reason、submitted_by_id、reviewed_by_id、created_time、updated_time。

必需约束：同一 target_dependency 最多一个 pending update/delete；同一拟创建有向对最多一个 pending create；update/delete 的 base_version 必须匹配正式边；批准 create/update 时在事务内重新防环和校验唯一性；approve 和 reject 的操作者均不得等于 submitted_by_id，自审返回 403 且不改变申请、正式边或审计。

### 3.2 KnowledgeMappingBatch

必需字段：UUID id、problem_id、batch_version、base_version、approved_version nullable、status、payload、submitted_by_id、reviewed_by_id、reason、created_time、updated_time。

`batch_version` 每次提交递增，驳回也占用。`approved_version` 只在批准时赋值并递增。客户端提交的 `base_version` 只引用 approved_version。批准时原子替换当前 ProblemKnowledge；驳回不改变当前集合。approve 和 reject 的操作者均不得等于 submitted_by_id，自审返回 403 且不改变批次、当前集合或审计。

### 3.3 KnowledgeReviewEvent

只追加事件表。object_type 只允许 knowledge_point、dependency_change、problem_mapping。快照必须通过知识模块快照 Schema，禁止写入答案、测试点、学生代码、Cookie 或令牌。

## 4 KnowledgeDependency 目标结构

正式边字段：id、prerequisite_id、dependent_id、relation_type、weight、source、confidence、version、created_by_id、created_time、updated_time。删除 review_status 和 reviewed_by 作为正式边状态字段，因为待审状态由变更申请持有；如上游为兼容保留 review_status，则正式行只能为 approved，业务代码不得依赖其他值。

数据库必须包含有向对唯一约束和 prerequisite_id 不等于 dependent_id 的检查约束。多节点环由领域服务在事务内检查。

## 5 迁移影响

当前提供的目录不是 Git 仓库，且未发现可验证的已部署知识表状态，因此本提案不假设生产中已有这些表。实施前，后端负责人必须确认实际数据库是否存在旧版知识表。

- 若尚未建表，直接按目标结构创建迁移。
- 若已有未投产空表，可在备份后用显式迁移调整约束与字段。
- 若已有业务数据，必须先导出数量、状态分布、重复有向对和环检测报告，再单独评审数据迁移；禁止 Agent 自动合并或删除冲突边。
- 历史题不回填空映射，不伪造主知识点。

## 6 批准和合入检查

后端架构负责人应在上游 `data-model-v1.md` 和迁移策略中逐项接受或拒绝 DM-01 至 DM-04、新增三个对象及正式依赖结构。合入后记录上游文档 commit 和前后端源码 commit，并在知识交付包 README 中补录。只有上游合入、OpenAPI 与 Schema 校验通过、产品、后端、前端和测试四方签字后，才能将本包冻结为 1.0.0。

## 7 拒绝提案时的处理

若任何修改未获批准，产品与后端必须共同回到 PRD 决策层调整需求。开发 Agent 不得自行保留部分目标模型、在服务层模拟缺失字段，或同时兼容两套互相矛盾的版本语义。
