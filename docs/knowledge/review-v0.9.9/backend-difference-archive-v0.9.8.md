# XMUOJ 知识点体系模块后端差异归档

- 文档版本：0.9.8
- 归档日期：2026-09-17
- 状态：待后端评审
- 用途：集中记录现有 XMUOJ 后端、冻结数据模型与知识点模块目标设计之间的差异
- 结论：本文件是评审输入，不是数据库迁移授权；全部阻断项关闭前，开发 Agent 不得创建模型或迁移

## 1. 归档范围与证据边界

本文件区分三类基线，避免把“文档设计”和“真实代码”混为一谈。

| 基线 | 位置 | 本次用途 |
|---|---|---|
| 现有 XMUOJ 后端源码 | `D:\Homework\da_chuang\XMUOJ\XMUOJBE-master\XMUOJBE-master` | 确认现有模型、权限、路由、响应基类和依赖版本 |
| 上游冻结数据模型 | `D:\Homework\da_chuang\2026.9.6\XMUOJ-AI-第一期后端契约交付-2026-08-11\docs\data-model-v1.md` | 确认原知识点表设计和冻结约束 |
| 本模块目标设计 | 本交付包 PRD、`knowledge-data-contract-v1.md`、OpenAPI 和快照 Schema | 确认已批准产品规则及目标后端行为 |

本次只进行了静态源码和文档扫描，没有连接开发、测试或生产数据库，也没有执行迁移。因此，“源码中未发现”不能证明数据库中一定不存在同名旧表；数据库现状仍需后端负责人核验。

## 2. 总体结论

1. 在所扫描的现有 XMUOJ 后端源码中，没有发现 `KnowledgePoint`、`KnowledgeDependency`、`ProblemKnowledge`、依赖变更申请、映射批次或知识审核事件的模型、迁移和 URL 注册。该模块对当前源码而言属于新增业务模块，不是简单页面扩展。
2. 上游冻结数据模型已经设计了 `KnowledgePoint`、`KnowledgeDependency` 和 `ProblemKnowledge`，但尚未在所扫描后端源码中落地。
3. 冻结模型与已确认产品规则至少存在四项已确认阻断冲突，并且存在若干需要后端明确选择的补充差异。
4. 现有账号角色、题目对象、`/api/` 与 `/api/admin/` 路由分层可以复用，但知识模块必须增加专用授权、响应适配、事务服务和审核数据结构。
5. 产品已确认 PRD D-01 至 D-16 的业务结论，其中提交人不得审核自己的依赖变更或题目标注申请；本文件中的待评审项只允许后端确认实现方式或提出显式契约变更，不得重新当作未决定的产品默认值。

## 3. 现有后端源码差异

| 编号 | 现有源码事实 | 目标设计 | 影响与处理 | 状态 |
|---|---|---|---|---|
| BE-01 | 未发现知识点相关模型、迁移、视图、序列化器或路由 | 新增知识点、正式依赖、依赖变更申请、当前题目映射、映射批次和审核事件 | 必须先确定 Django app 归属、表名和初始迁移；不得假设已有表可直接改造 | 阻断，待后端确认数据库现状 |
| BE-02 | 已有 `Regular User`、`Admin`、`Super Admin`，以及 `ProblemPermission.NONE/OWN/ALL` | 知识点与依赖维护、审核仅限 Super Admin；题目标注按 ALL/OWN/NONE 控制 | 复用现有角色，不新增“知识管理员”角色；必须增加知识模块专用权限判断，不能把 ALL 解释为知识体系维护权 | 产品规则已确认，待实现评审 |
| BE-03 | `Problem` 的展示编号 `_id` 是 `TextField`；比赛归属为 nullable `contest`；另有 `visible` 和 `created_by` | 主站关联题目仅返回 `contest_id IS NULL AND visible=True`；OWN 按 `created_by` 判断；对外字段名为 `display_id` | `display_id` 必须序列化自 `_id`，不得按整数处理；现有字段足以支持过滤和对象权限 | 已确认 |
| BE-04 | 全站 `APIView.success/error` 固定返回 `{error, data}`，默认通过 `HttpResponse` 返回；现有基类没有为知识契约统一设置 201、204、4xx 的机制 | OpenAPI 要求真实 HTTP 状态码、结构化业务错误以及 204 无响应体 | 新建 `KnowledgeAPIView` 或等价的模块内适配层；不得修改旧 `APIView`、`JSONResponse` 或全站响应语义 | 阻断，方案已由 PRD 固化 |
| BE-05 | 根路由已按 `/api/` 和 `/api/admin/` 分层，通过各 app 的 `urls.oj`、`urls.admin` 注册 | 主站知识查询走 `/api/knowledge/`；管理写操作走 `/api/admin/knowledge/` | 新模块沿用现有分层并独立注册 URL；不得向主站路径增加写方法 | 已确认 |
| BE-06 | 部署依赖为 Django 3.2.25、DRF 3.14.0、PostgreSQL 驱动 psycopg2 2.9.9；项目已有 `utils.models.JSONField` | 目标模型包含 JSON 快照、payload、aliases、metadata、检查约束和部分唯一约束 | 模型与迁移必须兼容 Django 3.2 和 PostgreSQL；JSON 字段按项目约定使用 `utils.models.JSONField`；约束写法须由后端验证 | 待技术评审 |
| BE-07 | 现有管理员接口主要复用 `admin_role_required`、`problem_permission_required` 和对象创建人检查 | 知识点目录和依赖写操作仅 Super Admin；题目标注还需题目对象范围检查；审核仅非提交人的 Super Admin | 增加模块级授权函数并对每个查询集做服务端过滤；approve/reject 必须比较当前用户与 submitted_by；前端隐藏按钮不构成授权 | 产品规则已确认，阻断待安全用例验证 |

## 4. 冻结数据模型的已确认冲突

以下差异已经由产品规则确认，不再交给开发 Agent 选择。

| 编号 | 上游冻结模型 | 目标设计 | 必须修改为 |
|---|---|---|---|
| DM-01 | `KnowledgePoint.status` 默认 `active` | 管理端新建知识点必须先进入草稿 | API 创建默认 `draft`；导入工具只有在显式审核规则允许时才能写入 `active` |
| DM-02 | `KnowledgeDependency` 唯一键为 `(prerequisite_id, dependent_id, relation_type)` | 同一有向知识点对只能存在一条正式边 | 唯一键改为 `(prerequisite_id, dependent_id)`；不能用不同 `relation_type` 绕过 |
| DM-03 | `KnowledgeDependency` 没有 `version` | update/delete 申请需要对正式边执行乐观锁 | 增加 `version`，创建时为 1，批准 update 后加 1 |
| DM-04 | 每道已发布题至少有一个 approved primary | 历史题允许未标注，不能阻断发布、展示、提交和判题 | “恰好一个 primary”仅约束已经存在当前生效映射集合的题目；无集合时派生为 `unannotated` |

## 5. 新发现的待后端评审差异

以下项目会影响数据库结构或迁移，但尚未形成单独的后端批准结论。它们必须在合入上游模型前逐项关闭，Agent 不得自行选择兼容方案。

| 编号 | 上游冻结模型 | 当前目标设计 | 待确认问题 |
|---|---|---|---|
| DR-01 | 正式 `KnowledgeDependency` 自带 `review_status` 和 `reviewed_by_id`，可保存 pending、approved、rejected | 正式表只保存当前 approved 边，审核状态由 `KnowledgeDependencyChangeRequest` 持有 | 是否从正式表删除两个审核字段；若为兼容保留，必须限制正式行只能为 approved，业务代码不得读取其他状态 |
| DR-02 | 依赖 `weight` 检查为 `0 <= weight <= 1` | 目标契约为 `0 < weight <= 1` | 是否禁止 0；若禁止，需修改数据库检查约束和迁移前数据检查 |
| DR-03 | 正式依赖记录 `reviewed_by_id`，没有 `created_by_id` | 目标正式边记录批准 create 的审核者为 `created_by_id` | 最终采用哪个归属字段、旧数据如何映射，以及删除用户时使用 SET_NULL 还是 PROTECT |
| DR-04 | `ProblemKnowledge` 逐行保存 pending、approved、rejected，并逐行记录审核人 | 目标表只保存当前 approved 集合；整组候选数据保存在 `KnowledgeMappingBatch.payload` 中审核并原子替换 | 是否批准从逐行审核改为批次审核；若批准，应禁止把 pending 行混入正式表 |
| DR-05 | 冻结模型只明确“已被引用的知识点不得物理删除”，设计原则倾向软停用 | 目标允许从未被任何业务或历史对象引用的 draft 在审计后物理删除 | 未引用 draft 的物理删除是否获得后端批准；如拒绝，需要同步修改 PRD、OpenAPI、数据契约和 AC-28/29 |
| DR-06 | 冻结模型没有依赖变更申请、映射批次和统一知识审核事件 | 目标新增 `KnowledgeDependencyChangeRequest`、`KnowledgeMappingBatch`、`KnowledgeReviewEvent` | 确认表名、字段类型、索引、外键删除策略、快照保留周期及迁移顺序 |
| DR-07 | 冻结模型的 `ProblemKnowledge` 不保存 batch_version、base_version、approved_version | 目标采用提交批次版本与批准版本分离 | 确认并发锁以 approved_version 为准；驳回只消耗 batch_version，不递增 approved_version |
| DR-08 | 冻结模型没有规定提交人与审核人必须不同 | 产品已确认依赖变更和题目标注均禁止提交人 approve 或 reject 自己的申请 | 确认对象级权限校验、403 `KNOWLEDGE_SELF_REVIEW_FORBIDDEN`、详情 capabilities、提交人与审核人字段约束及正反向测试 |

## 6. 新增目标对象摘要

| 对象 | 责任 | 不得混入的职责 |
|---|---|---|
| `KnowledgePoint` | 保存知识点当前状态和乐观锁版本 | 不保存依赖审核状态或题目标注批次 |
| `KnowledgeDependency` | 只保存当前正式生效边 | 不保存 pending/rejected 申请 |
| `KnowledgeDependencyChangeRequest` | 保存依赖 create/update/delete 申请及审核状态 | 批准前不得直接改正式边 |
| `ProblemKnowledge` | 只保存题目当前 approved 映射集合 | 不保存待审或已驳回候选集合 |
| `KnowledgeMappingBatch` | 保存一次完整题目标注提交、双版本及审核状态 | 不替代当前正式映射查询 |
| `KnowledgeReviewEvent` | 保存只追加、受限快照的审计事件 | 不作为当前业务状态来源，不保存答案、测试点、学生代码、Cookie 或令牌 |

## 7. 迁移前必须取得的事实

后端负责人应在真实目标环境执行只读核验，并把结果填写到本节或单独附上报告：

1. 数据库是否已经存在 `knowledge_point`、`knowledge_dependency`、`problem_knowledge` 或同义旧表。
2. 各表记录数量、状态分布、字段类型、约束、索引和外键删除策略。
3. 是否存在同一有向点对的多 relation_type 重复边、零权重边、自环或多节点环。
4. 是否存在逐行 pending/rejected 的题目标注数据，以及每题 approved primary 的数量分布。
5. 是否存在依赖或映射数据无法映射到当前 `Problem`、`User` 或知识点记录。
6. 实际 PostgreSQL 版本、迁移执行账号权限、备份和回滚方式。

若存在业务数据，只允许先生成差异报告和迁移方案；禁止 Agent 自动删除、合并、补造主知识点或批量改状态。

## 8. 后端评审关闭条件

每项必须记录“接受、拒绝或修改后接受”、评审人、日期和对应 commit/变更单：

- [ ] 核实 BE-01 的真实数据库现状。
- [ ] 接受并合入 DM-01 至 DM-04。
- [ ] 对 DR-01 至 DR-08 逐项形成明确结论。
- [ ] 确认六个目标对象的表结构、索引、约束和外键策略。
- [ ] 确认 `KnowledgeAPIView` 的 HTTP 状态码和旧响应兼容方案。
- [ ] 确认权限矩阵、对象范围过滤和 401/403/404 防枚举策略。
- [ ] 评审数据迁移、备份、回滚和上线顺序。
- [ ] 更新上游 `data-model-v1.md`、迁移规范、OpenAPI、数据契约和测试计划。
- [ ] 在真实 Git 仓库记录 40 位 commit，并将本交付包冻结为 1.0.0。

## 9. Agent 执行边界

在第 8 节全部关闭前：

- 不得创建或修改知识模块数据库迁移。
- 不得在服务层同时兼容两套冲突的数据模型。
- 不得把 pending/rejected 数据写入或查询为主站正式数据。
- 不得修改全站 `APIView`、`JSONResponse`、既有账号角色或既有题目字段语义。
- 不得自行决定 DR-01 至 DR-08；发现代码与本文件不一致时必须停止并提交契约变更。

## 10. 关联文件

- `data-model-change-proposal-v0.9.8.md`：上游模型正式变更提案。
- `knowledge-data-contract-v1.md`：目标字段、约束、事务和查询口径。
- `knowledge-api-v1.yaml`：接口与错误响应机器契约。
- `knowledge-snapshot-schema-v1.json`：审核快照边界。
- `XMUOJ知识点体系模块PRD_v0.9.8.md`：产品规则唯一可编辑源文件。
