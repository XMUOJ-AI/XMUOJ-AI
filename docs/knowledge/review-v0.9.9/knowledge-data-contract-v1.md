# XMUOJ 知识点体系模块数据契约

- 版本：0.9.9
- 状态：待评审
- 更新日期：2026-09-17
- 适用范围：知识点、正式知识依赖、依赖变更申请、题目知识点映射、映射审核批次、审计事件及主站只读投影

## 1 权威来源和冲突处理

本文件是产品模块的目标实现摘要，不是已批准的上游数据库模型。既有冻结 `docs/data-model-v1.md` 第 5 节与本需求存在四项冲突：KnowledgePoint API 默认状态、KnowledgeDependency 唯一键、KnowledgeDependency version、历史题是否必须补标。`data-model-change-proposal-v0.9.8.md` 还新增 `KnowledgeDependencyChangeRequest`、`KnowledgeMappingBatch` 和 `KnowledgeReviewEvent`。提案未合入上游前，开发 Agent 必须停止，不得据本摘要创建迁移。

冲突优先级：批准后的数据库模型与迁移 > 批准后的 OpenAPI 和快照 Schema > 本摘要 > 示例。发现冲突时停止实现并发起契约变更，不得静默兼容。

权限边界：ALL、OWN、NONE 是既有 `ProblemPermission` 的枚举值，只限定普通 Admin 的题目标注对象范围，不是独立角色。知识点目录、依赖关系和审核的写操作仅允许 Super Admin；Admin+ALL 可标注全部普通题，Admin+OWN 仅可标注本人创建的普通题，Admin+NONE 不可访问管理员端知识模块。已登录 Regular User 和包括 NONE 在内的所有管理账号都可访问主站已生效只读投影；未登录用户不可访问，主站 API 返回 401。不得用 `ProblemPermission.ALL` 推导知识体系维护或审核权限。

## 2 KnowledgePoint

| 字段 | 类型 | 规则 |
|---|---|---|
| id | AutoField | 内部主键，不作为可编辑业务标识 |
| code | varchar(64) | 全局唯一，`^[a-z][a-z0-9_]{0,63}$`，创建后不可修改 |
| name | varchar(128) | 1 至 128 字符 |
| normalized_name | varchar(128) | 按本节固定算法由服务端生成，全局唯一 |
| description | text | 默认空字符串，描述定义、范围和不包含内容 |
| category | varchar(32) | basic、data_structure、algorithm、paradigm、mathematics、string、graph |
| level | smallint | 1 至 5；表示知识层级，不表示题目难度 |
| status | varchar(16) | draft、active、deprecated |
| version | integer | 初始 1；任一可编辑字段修改成功后加 1，用于乐观锁 |
| aliases | jsonb | 字符串数组，按规范化值去重后保存原显示值 |
| metadata | jsonb | 扩展元数据；一期只允许 `course_chapter`、`display_order` |
| created_by_id | FK user | 允许空以兼容迁移；API 创建时必须记录当前用户 |
| created_time / updated_time | timestamptz | 服务端生成 |

`normalized_name` 固定算法：先做 Unicode NFKC；删除首尾 Unicode 空白；将连续 Unicode 空白折叠为单个 ASCII 空格；仅将 ASCII `A-Z` 转为小写；保留中文、数字和标点，不得自行移除标点或做拼音转换。结果为空或超过 128 字符时拒绝请求。

状态机：仅允许 `draft -> active`、`active -> deprecated`；一期不允许逆向恢复。只有从未被任何正式依赖、依赖变更申请、`ProblemKnowledge` 或映射批次引用的 draft 可由 Super Admin 物理删除；active/deprecated 即使暂时无引用也禁止删除。管理端 POST 删除命令必须在 JSON 体携带当前 version 和 2 至 500 字原因，在同一事务锁定对象、复核全部引用、写 knowledge_point/deleted 事件与受限前后快照，再删除；状态、引用或版本冲突均返回 409 并不写审计。active 转 deprecated 是服务层受控操作：引用该点的 pending 依赖变更申请、pending 映射批次、当前正式依赖或当前 `ProblemKnowledge` 映射仍存在时返回 409；先处理待审对象、通过变更申请删除或变更正式依赖，并通过新批次替换当前映射。历史 rejected/superseded 批次和审计事件保留。

## 3 KnowledgeDependency

`prerequisite -> dependent` 表示学习 dependent 前应掌握 prerequisite。

| 字段 | 类型 | 规则 |
|---|---|---|
| id | AutoField | 正式边内部主键 |
| prerequisite_id / dependent_id | FK knowledge_point | 正式边两端必须 active；不得相同 |
| relation_type | varchar(16) | required、recommended |
| weight | numeric(4,3) | 大于 0 且小于等于 1 |
| source | varchar(16) | manual、import、ai；本期审核创建时固定 manual，客户端不可输入 |
| confidence | numeric(4,3) | 本期固定 1.000，客户端不可输入 |
| version | integer | 初始 1；批准 update 后加 1，用于变更申请乐观锁 |
| created_by_id | FK user | 批准 create 申请的审核者，PROTECT |
| created_time / updated_time | timestamptz | 服务端生成 |

该表只保存当前正式生效边，不保存 pending 或 rejected 数据。唯一键为 `(prerequisite_id, dependent_id)`，同一有向知识点对不得以不同 relation_type 建两条边。数据库阻止自环，领域服务在批准 create/update 的事务内阻止任意多节点环。所有图查询均以本表为正式边来源。

`source` 和 `confidence` 不构成本期产品功能。不得为其增加页面控件、自动生成流程、条件分支或额外接口。

## 4 KnowledgeDependencyChangeRequest

该表是所有依赖 create、update、delete 的审核对象。申请批准前，正式 `KnowledgeDependency` 不改变。

| 字段 | 类型 | 规则 |
|---|---|---|
| id | UUID | 主键，uuid4；API 中称 request_id |
| operation | varchar(16) | create、update、delete |
| target_dependency_id | FK knowledge_dependency | update/delete 必填，create 为空；SET_NULL 以保留已批准 delete 历史 |
| base_version | integer | update/delete 必填并等于提交时正式边 version；create 为空 |
| prerequisite_id / dependent_id | FK knowledge_point | create/update 必填，delete 为空；提交与批准时均须 active |
| relation_type | varchar(16) | create/update 必填；required、recommended |
| weight | numeric(4,3) | create/update 必填；大于 0 且小于等于 1 |
| status | varchar(16) | pending、approved、rejected |
| reason | text | 提交理由 2 至 500 字；驳回理由保存在 review_reason |
| review_reason | text | reject 时 2 至 500 字；approve 时为空 |
| submitted_by_id / reviewed_by_id | FK user | 提交人必填；审核前 reviewed_by 为空，审核后 reviewed_by 不得等于 submitted_by，均 PROTECT |
| created_time / updated_time | timestamptz | 服务端生成；updated_time 用于审核并发控制 |

约束：同一 target_dependency 最多一个 pending update/delete 申请；同一拟创建有向对最多一个 pending create 申请。提交 create 时不得存在同向正式边；提交 update/delete 时 target 与 base_version 必须匹配。approve 和 reject 的操作者都不得等于 submitted_by_id；提交人自审返回 403 `KNOWLEDGE_SELF_REVIEW_FORBIDDEN`，申请、正式边和审计均不改变。其他 Super Admin 批准时锁定申请、目标边及涉及的知识点，并再次校验版本、唯一性和防环。批准 create 创建 version=1 的正式边；批准 update 更新正式边并将 version 加 1；批准 delete 删除正式边。申请失败或被驳回时正式边和审计均不发生半成品变化。

## 5 ProblemKnowledge

`ProblemKnowledge` 只保存当前生效的题目映射集合。待审核和已驳回的集合保存在 `KnowledgeMappingBatch.payload`，不得与当前集合混写。

| 字段 | 类型 | 规则 |
|---|---|---|
| problem_id | FK problem | 一期仅普通题，即 contest 为空 |
| knowledge_point_id | FK knowledge_point | 创建或批准当前集合时必须 active；当前集合存在期间不得将其废弃 |
| role | varchar(16) | primary、secondary、prerequisite |
| weight | numeric(4,3) | 大于 0 且小于等于 1；集合不要求和为 1 |
| source | varchar(16) | 冻结模型兼容字段；本期接口只写 manual，不接受客户端输入 |
| confidence | numeric(4,3) | 冻结模型兼容字段；本期固定写 1.000，不展示、不计算且不接受客户端输入 |
| review_status | varchar(16) | 当前表中必须为 approved |
| reviewed_by_id | FK user | 批准当前集合的审核者 |

唯一键为 `(problem_id, knowledge_point_id)`。只要题目存在当前生效集合，该集合就必须且只能有一个 approved primary。集合消费者按 approved 权重确定性归一化：`normalized_weight = weight / sum(all approved weights)`。

历史兼容：没有当前生效集合的普通题为 `unannotated`，可以继续按旧系统发布、展示、提交和判题。存在 pending 批次但尚无生效集合时为 `in_review`；存在生效集合时为 `ready`。一期不得把“所有已发布历史题都必须已标注”作为数据库迁移或发布前置条件。

## 6 KnowledgeMappingBatch

该表保存一次题目映射集合提交，是审核对象和并发边界；同一题目的旧 approved 集合在新批次审核完成前继续生效。

| 字段 | 类型 | 规则 |
|---|---|---|
| id | UUID | 主键，uuid4；API 中称 review_batch_id |
| problem_id | FK problem | 一期仅普通题，PROTECT |
| batch_version | integer | 同一题目每次提交从 1 递增；驳回和 superseded 也占用；`(problem_id, batch_version)` 唯一 |
| base_version | integer | 提交者编辑时看到的 approved_version；未标注题为 0 |
| approved_version | integer nullable | 仅批准时赋值为该题当前批准版本加 1；pending、rejected 为 null |
| status | varchar(16) | pending、approved、rejected、superseded |
| payload | jsonb | 完整映射集合，必须符合 `mapping_batch_snapshot` JSON Schema |
| submitted_by_id | FK user | 提交人，PROTECT |
| reviewed_by_id | FK user | 审核前为空，审核后记录且不得等于 submitted_by_id，PROTECT |
| reason | text | 驳回时 2 至 500 字，其他状态为空字符串 |
| created_time / updated_time | timestamptz | 服务端生成 |

约束：同一题目最多一个 pending 批次；提交时 `base_version` 必须等于当前 approved_version；批准时再次校验。approve 和 reject 的操作者都不得等于 submitted_by_id；提交人自审返回 403 `KNOWLEDGE_SELF_REVIEW_FORBIDDEN`，批次、当前集合和审计均不改变。当前 approved_version 取该题已批准或 superseded 批次中最大的非空 approved_version，没有时为 0。其他 Super Admin 的批准操作在同一事务内锁定题目和批次，原子替换 `ProblemKnowledge` 当前集合，将上一 approved 批次改为 superseded，并将新批次改为 approved，同时设置 approved_version。驳回只消耗 batch_version，不改当前集合或 approved_version。

示例：batch 1 批准后 approved_version=1；batch 2 驳回后批准版本仍为 1；batch 3 批准后 approved_version=2。客户端 base_version 始终引用 approved_version。

## 7 KnowledgeReviewEvent

该表只记录事件，不代替依赖关系或映射批次的当前业务状态。

| 字段 | 类型 | 规则 |
|---|---|---|
| id | UUID | 主键，uuid4 |
| object_type | varchar(24) | knowledge_point、dependency_change、problem_mapping |
| object_key | varchar(64) | knowledge_point 使用 code；dependency_change 使用申请 UUID；problem_mapping 使用批次 UUID |
| object_version | integer | knowledge_point 使用对象 version；dependency_change 使用目标边批准前或批准后的 version，无正式边时为 0；problem_mapping 使用 batch_version |
| action | varchar(16) | submitted、approved、rejected、replaced、deleted |
| reason | text | rejected、replaced、deleted 时 2 至 500 字；其他动作允许空字符串 |
| actor_id | FK user | 当前操作人，PROTECT |
| snapshot | jsonb | 必须符合对应 JSON Schema，不含题目答案、测试点、学生代码、Cookie 或令牌 |
| request_id | varchar(64) | 关联 API 请求日志；建立索引但不要求唯一 |
| created_time | timestamptz | 服务端生成 |

审计事件只追加，不允许通过业务 API 更新或删除。索引：`(object_type, object_key, object_version, created_time)`、`actor_id`、`request_id`。

## 8 快照 Schema

机器可读定义见 `knowledge-snapshot-schema-v1.json`。`knowledge_point_delete_snapshot` 只用于删除未使用草稿，before 仅有 code、name、category、level、status、version，after=null。`dependency_change_snapshot` 包含 request_id、operation、target_dependency_id、base_version、before、proposed、status；before 与 proposed 使用同一正式边结构并允许按 operation 为 null。`mapping_batch_snapshot` 包含 review_batch_id、problem_id、batch_version、base_version、approved_version、status 和 mappings。服务端拒绝 Schema 之外的字段，避免把答案、测试点、学生代码、Cookie 或令牌写入审计表。

## 9 原子性和并发

- 题目映射按批次整体提交，任何一项失败则整体回滚。
- 依赖变更申请提交不改变正式边；批准时防环检查、正式边写入和审计事件在同一事务内完成。
- 依赖变更和题目标注的提交人均不得 approve 或 reject 自己的申请；后端按 submitted_by_id 执行对象级校验，不能只依赖前端隐藏按钮。
- 知识点更新和删除携带 version；依赖 update/delete 申请携带 target 的 base_version；审核携带申请 updated_time。
- 映射提交携带 base_version；同一题目最多一个 pending 批次。
- 并发冲突返回 409，不使用最后写入覆盖。

## 10 已批准数据的变更和删除

- 知识点：仅可物理删除从未被业务引用的 draft；已引用时 PROTECT。active 即使已清理当前引用，也只能 deprecated；deprecated 保留历史，不得物理删除。
- KnowledgeDependency：没有直接更新或删除 API。Super Admin 对 create/update/delete 均提交 `KnowledgeDependencyChangeRequest`；update/delete 批准前旧正式边继续生效，批准时才原子切换。原因、并发或校验失败时正式边不变。
- ProblemKnowledge：只能通过批准 KnowledgeMappingBatch 原子替换，禁止逐行编辑或删除当前集合。

## 11 当前生效数据查询

普通查询不得直接拼接审核表来推断当前状态。统一领域查询服务只返回 active 知识点、两端 active 的正式依赖和 `ProblemKnowledge` 当前集合；pending/rejected 依赖申请及 pending/rejected/superseded 映射批次只能通过审核或历史查询读取。主站关联题目还必须过滤 `Problem.contest_id__isnull=True, visible=True`。`unannotated` 与 `in_review` 不影响题目发布、展示、提交和判题。

## 12 主站只读投影与信息边界

主站三个 GET API 必须先校验 Session，再分别从已生效知识点、依赖及题目映射生成独立只读投影，不得把管理员端 `KnowledgePoint`、审核批次或审计事件序列化结果直接返回。没有有效 Session 时统一返回 401；请求 draft、deprecated 或不存在的知识点详情统一返回 404。主站没有写接口；管理员端写 API 继续按角色及对象授权。

| 投影 | 允许字段 | 后端过滤 |
|---|---|---|
| PublicKnowledgePoint | code、name、description、category、level、aliases | status=active；不返回 id、normalized_name、status、version、metadata、创建/更新时间及审核字段 |
| PublicKnowledgePointDetail | PublicKnowledgePoint 字段、prerequisites、dependents、related_problems | 关系只取两端 active 的正式边，摘要按对方 code 升序；题目只取当前 approved 映射与 visible 普通题，按 Problem._id 升序 |
| PublicDependencySummary | code、name、relation_type、weight | 不返回依赖内部 id、review_status、reviewed_by、source、confidence、version 或审计 |
| PublicProblemSummary | display_id、title | display_id 使用 `Problem._id`；只取 `contest_id__isnull=True, visible=True`，不得泄露隐藏题或比赛题的编号、标题与计数 |
| PublicKnowledgeGraph | nodes、edges、truncated | 节点 active；边来自正式依赖且两端 active；边不返回内部 id；节点至多 500 |

主站列表按 code 升序，分页默认 20、上限 100；搜索范围与管理列表一致，但主站不接收 status。图谱 depth 默认 3、上限 8。有 root_code 时，先在 active 正式图中从根同时沿 prerequisite 上游与 dependent 下游遍历；根距离为 0，一条边距离为 1；达到 depth 后对非根节点应用 category/level，根始终保留。root_code 不存在或非 active 时返回 404。无 root_code 时 category/level 过滤全部 active 节点，depth 被忽略。候选超过 500 时按 `(distance, code)` 取前 500 个；无根时距离统一为 0。边按 `(from, to)` 排序且两端必须都在节点集合中，不得返回悬空边。`/knowledge` 的局部图调用只使用 root_code 与 depth；category/level 仍保留在接口中供 `/knowledge/graph` 完整图谱使用。前端展示管理跳转依据现有已认证身份；服务端知识权限不依赖该按钮是否显示。

## 13 管理查询和审核投影

管理列表项包含正式依赖和当前映射口径下的 `prerequisite_count`、`dependent_count`、`related_problem_count`。管理详情在基础字段外返回 `capabilities`、前置摘要、后继摘要和按题目对象权限过滤的关联题目摘要；每类摘要返回稳定排序、受限 items 和 total。实现使用聚合或 prefetch，禁止按知识点或摘要逐行查询。

审核队列只返回摘要，不返回完整 payload。筛选字段固定为 `object_type`、`submitter_id`、`status`、`updated_from`、`updated_to`、`keyword`；object_type 只允许 `dependency_change` 与 `problem_mapping`。审核详情按 object_type 返回可判别结构：dependency_change 包含正式边 before、proposed、operation 与 base_version；problem_mapping 包含题目摘要、batch_version、base_version、当前 approved_version 与完整 mappings。两类详情都返回 `capabilities`；当前用户等于提交人时数组不含 `approve` 或 `reject`。该字段只控制页面展示，审核接口仍独立校验并在自审时返回 403。

知识模块新接口由专用后端响应基类生成统一包络，并由前端专用适配器解析。不得修改旧接口使用的全局响应类或 ajax。204 响应不含 body；前端适配器必须将其解析为空结果，不尝试读取 JSON。
