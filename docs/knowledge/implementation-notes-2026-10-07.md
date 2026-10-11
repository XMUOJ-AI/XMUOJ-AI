# 知识点工作契约与实施说明

用户已授权继续完成项目后端，并暂缓跨团队确认和版本冻结。本说明记录当前实施选择，不代表上游批准、四方签字或 1.0.0 冻结。原始 [review-v0.9.9](review-v0.9.9/README.md) 目录保持字节不变，继续作为来源和历史评审证据；实现使用下面的工作文件。

- [knowledge-api-v1.yaml](../openapi/knowledge-api-v1.yaml)：OpenAPI 3.0.3，`info.version=0.9.9`，`x-contract-status=implementation-working-draft`，本次修订 `x-contract-revision=2026-10-07-H5`。
- [knowledge-snapshot-schema-v1.json](../schemas/knowledge-snapshot-schema-v1.json)：Draft 2020-12，`x-contract-version=0.9.9`，同样为工作草案。
- [完整后端矩阵](../plans/backend-completion-matrix.md)：四份工作OpenAPI合计36个HTTP操作（含本次2个公开分页入口）、17个工具名称与28个基线模型责任项；知识模块仅为其中一部分，该操作数不包含旧站其他管理API。

现有源码和旧契约的其余规则继续适用。本说明只解决已识别的可执行性问题，不改变登录要求、角色、禁止自审、只读主站、每题一个 primary、历史题可未标注、正式依赖审核、双版本、知识点状态机或图谱 500 节点上限。

## 机器定义修正

| 评审项 | 工作定义 | 业务含义 |
| --- | --- | --- |
| CR-01 | nullable 对象使用有同层 `type: object` 的独立 nullable component，避免把 `nullable` 写在非空 allOf 外层 | 无 pending 批次、待审 reviewer、create 的 before、delete 的 proposed 可以合法返回 null；仍拒绝错误类型和缺字段对象 |
| CR-02 | ReviewDetail 添加 dependency_change/problem_mapping 的显式 discriminator mapping | 两类审核详情按原业务枚举正确解析 |
| CR-07 | DependencyChangeRequestInput 使用 create/update/delete 三个互斥完整输入分支 | 每种操作严格 required + additionalProperties=false；create 不收 target/base，delete 不收拟变更字段，所有输入拒绝 null 替代必填值 |
| CR-05 | PublicKnowledgePoint 与公开详情均增加 prerequisite_count/dependent_count；两类 GraphNode 增加 category | 计数为正式 active 图中完整直接邻接总数，不从截断后的图推导；公开字段仍不含管理版本/状态/身份 |
| CR-05 | KnowledgePoint 增加 nullable created_by: UserSummary；MappingSetEnvelope.data 增加 problem: ProblemReviewSummary | 创建人的历史空值可兼容；题目标注接口直接提供数据库主键、字符串展示编号和标题。公开状态、难度、标签等扩展题目信息复用有权的既有题目详情接口，不扩入公共投影 |
| CR-08 | 管理 GraphEdge 增加 version；增加邻接分页、关联题分页、单正式边读取 | 有限摘要之外存在完整读取路径；编辑申请可取得准确 base_version |

依赖权重原本已有 `multipleOf: 0.001`，本次没有将其误当作缺失。服务端使用 Decimal 处理和校验三位精度；不把浮点二进制误差当成业务非法值。映射唯一 code 和恰好一个 primary 仍由领域服务检查；Schema 的结构校验不代替跨条目约束。

CR-08 补充的三项管理读取接口均位于 `/api/admin/`，仅允许 Super Admin、Admin+ALL、Admin+OWN；H5 公开分页接口另见下一节：

| 操作 | 响应 data | 排序与权限 |
| --- | --- | --- |
| `GET /knowledge-points/{knowledge_code}/dependencies` | `{items: AdminDependencySummary[], page, page_size, total}` | direction=prerequisites/dependents，默认 prerequisites；对方 code、dependency_id 升序 |
| `GET /knowledge-points/{knowledge_code}/related-problems` | `{items: AdminProblemSummary[], page, page_size, total}` | display_id、problem_id 升序；先按普通题和调用者题目权限过滤再计数 |
| `GET /knowledge-dependencies/{dependency_id}` | 当前 `Dependency`，含准确 version | 删除或不存在返回 404；历史关系从审核详情读 |

前两个接口默认 page=1、page_size=20，上限 100。原详情摘要仍可限 100 项，total 与新增分页查询、管理列表计数保持相同权限口径；不能以只展示摘要为由遗漏第 101 项。Admin+NONE 不能访问这些管理接口，但仍可访问已登录主站只读投影。

## H5 公开集合的有界读取

这是2026-10-07 H5修订，机器文件使用 `x-contract-revision=2026-10-07-H5` 和 `x-contract-change-history` 记录新增接口与大集合行为变化；工作契约仍为0.9.9未冻结草案，本次不改原交付包或宣称冻结。新增公开接口面向全部已登录身份（含Admin+NONE），权限投影始终一致：

| 操作 | 响应data | 排序与范围 |
| --- | --- | --- |
| `GET /api/knowledge-points/{knowledge_code}/related-problems` | `{items: PublicProblemSummary[], page, page_size, total}` | 当前approved映射中的visible普通题，先过滤隐藏/比赛/pending候选再计数；display_id、problem_id升序；只输出display_id/title |
| `GET /api/knowledge-points/{knowledge_code}/dependencies` | `{items: PublicDependencySummary[], page, page_size, total}` | direction=prerequisites/dependents，默认prerequisites；只读正式active邻接；对方code、依赖id升序 |

两者page默认1、page_size默认20，上限100；超出最后一页返回空items及真实total。未知、重复、越界参数返回400；匿名401；draft/deprecated/不存在知识点统一404。offset分页保证同一数据状态下顺序稳定，不把多次请求包装成冻结快照；集合变更后客户端应重新加载。

原公开详情 `GET /api/knowledge-points/{code}` 的默认请求保留三种集合的数组类型，且每类不超过100时仍返回完整集合。任一可见集合超过100，返回明确的409 `KNOWLEDGE_PAGINATION_REQUIRED`；details含 `collection_limit`、超限的 `collections`、对应 `endpoints` 和 `detail_url`。数据库最多物化每类101项判断边界，不先加载全量再报错。新调用方可以显式请求 `?include_collections=false` 读取详情，此时三个数组都为空，prerequisite_count/dependent_count仍为真实邻接总数；完整关联题total从分页接口获得。参数只接受小写true/false，不接受重复值、0/1或宽松布尔转换。此方式不会静默截断旧数组，也不把数组改成分页对象。

仓库调用方追踪：公开详情仅由 `knowledge/views.py` 调用，旧前端当前未集成知识详情；Agent读取ORM及受控RAG接口，不依赖该公开详情。现有小集合测试保持原字段集合；新增大集合调用必须处理明确的分页错误或显式关闭内嵌。管理详情继续使用原有 `{items,total}` 有限摘要与管理分页，不改变其权限。

## 不可变历史与当前状态

依赖变更请求持久化 `before`、`proposed` 和 `original_target_id`。三者在成功提交后不可修改；审核只改变申请状态、审核人、审核原因和审核时间。update/delete 的 original_target_id 是提交时正式边 ID，永远保留；create 为 null；create 批准后这两个目标标识仍为 null，创建结果由拟建端点及批准事件追溯。`target_dependency_id` 是可空当前外键，正式边删除时可 SET_NULL，不能用它覆盖历史身份。

`before` 是受限 DependencyState：prerequisite_code、dependent_code、relation_type、weight、source、confidence、version、updated_time。它记录提交时正式边状态，不嵌入当前 KnowledgePoint 对象，不因知识点改名或边更新而漂移。`proposed` 仅包含拟变更的两个 code、relation_type、weight；create 的 before=null，delete 的 proposed=null。

审核事件的 dependency_change snapshot 统一使用 `original_target_id`，不使用可被清空的当前目标 FK。update/delete 快照要求 original_target_id 为正整数、before 完整；create 的 original_target_id/base_version/before 均为 null。approve 的版本校验保证生效前关系与申请基线一致；历史查询直接读取申请的不可变数据，不能重新用当前正式边拼造 before。

KnowledgeMappingBatch.payload 仅保存不可变的 `MappingBatchItem[]` 候选数组，使用 `$defs/mapping_payload` 校验，服务端写入 source=manual、confidence=1。payload 不重复保存 status、batch_version、base_version 或 approved_version。完整 API MappingBatch 与 mapping_batch_snapshot 均由权威模型列和 payload 组合生成；事件生成后不可更新，后续 superseded 不回写以前事件。

每次成功提交、批准和驳回写相应 submitted/approved/rejected 事件；替换已有 approved 批次时，旧批次转 superseded，并为旧批次写 replaced 事件，新批次写 approved 事件。replaced 原因可由服务端固定生成为“被新批准批次 {UUID} 替换”，无需给批准请求新增客户端 reason。映射事件 object_version 始终使用对应 batch_version；依赖申请提交/驳回使用基线版本（create 为 0），批准 create/update 使用新正式版本，批准 delete 使用被删边版本。拒绝自审、无权限、版本冲突和校验失败均不写业务或审核事件。

草稿删除仍使用原受限 knowledge_point 删除快照，只包含 code、name、category、level、status、version 和 after=null；不可把描述、metadata、题解、学生代码或凭证混入审核快照。

## 查询与并发实现要求

管理列表按 updated_time 倒序、code 升序。审核队列默认 status=pending，按 created_time、object_key 升序；updated_from/updated_to 为包含端点的时间区间，反向范围返回参数错误。审核 keyword 仅匹配依赖两端 code/name、题目展示编号/标题或提交者 username，不搜索候选 payload 或敏感内容。审核队列、详情与审核动作均只允许 Super Admin；普通 Admin 不能因为拥有题目就读取审核详情。

所有图结构变更必须通过同一个数据库事务级串行化机制进行防环检查和写入，不能只锁各申请自己的端点。知识点废弃检查与依赖/映射新增引用共享知识点锁协议，按稳定顺序取锁并在锁内复核 active 与引用。题目映射提交/批准锁定题目、批次和涉及知识点，批次分配、旧集合替换及事件写入在同一事务内完成。实际锁实现及 PostgreSQL 两连接并发测试由后端代码交付；本说明不将纯图模拟当作数据库通过证据。

导入候选不得写入 pending/rejected ProblemKnowledge。导入模块需通过知识领域服务或明确候选暂存层接入；不满足完整集合或审核条件时保留候选/警告，不自动批准、不伪造 primary，也不破坏已有 approved 集合。

## 旧工作 API 的 null 修正

本次同时检查了旧三份工作 API，按父任务授权在保留的工作文件修正以下既有业务语义的机器表达；旧交付 ZIP 和完整旧库归档保持不变，接口路径、operationId 与 1.0.0 版本号不变。这些是原本声明允许 null 的校正，不是对外宣告了新冻结或新部署。

- [learning-api-v1.yaml](../openapi/learning-api-v1.yaml)：LearningPath.target 原 nullable+allOf 会拒绝 null，改为 KnowledgeRef 或显式 null 的 oneOf。
- [agent-api-v1.yaml](../openapi/agent-api-v1.yaml)：Run.result 原外层 nullable+oneOf 会拒绝 queued 状态的 null，补显式 null 分支；Run.error_detail 同样修正。
- [problem-import-api-v1.yaml](../openapi/problem-import-api-v1.yaml)：Batch.validated_time/committed_time、CollectedProblem.imported_problem_id 和 PageMeta.next_cursor 的 null 本来就能通过，无需进行 null 修正；后续 H2 的批次权限修订不改变这些属性。

HTTP error 包络继续是错误码字符串 `error`、`data={message,retryable,details}`、`request_id`；Agent 内部工具返回的 error 对象属于另一套明确接口，不能混为 HTTP 包络。

## 初期机器校验与当前验证入口

初期标准验证器完成过 29 项工作契约检查：4 份 OpenAPI 元验证、知识快照元验证、合法/非法操作输入、两种审核判别、正常 nullable 响应、历史 delete 快照、候选数组结构、公开字段隔离、分页结果、完整 queued Agent 响应与空目标 LearningPath 等，29/29 达到预期（非法反例应被拒绝）。另对旧三份 API 的 7 个 nullable 属性进行前后检查；修正后三个原失败属性通过，四个导入属性保持通过。

上述初期结果来自当时 scratch 中的 `working-contract-probe.py`、`working-contract-probe-results.json`、`legacy-null-probe.py`、`legacy-null-before.json`、`legacy-null-after.json`，只证明当时的机器契约断言，不作为当前业务验收依据。当前仓库复现入口为 `tools/problem_batch/validate_contracts.py` 和各 Django 模块测试；H5 的知识25项、RAG17项、响应Schema及性能验证已归档在 [H5证据](../reviews/backend-h1-h7-evidence-2026-10-07/h5/README.md)。真实外部模型/Milvus未由这些本地检查证明。

`tools/problem_batch/validate_contracts.py` 已按文件检查预期版本：知识为0.9.9，其余三个工作API为1.0.0。H5修订后运行输出 `contract validation passed`，见 [原始结果](../reviews/backend-h1-h7-evidence-2026-10-07/h5/contracts.txt)；初期统一断言1.0.0导致的失败已修复，没有为绕过检查而修改知识工作稿版本。

## Agent 会话入口补充

用户授权实施后，为让现有 `SocraticHintRunRequest.conversation_id` 能通过正常链路获得，Agent 工作 API 增补 `POST /api/agent/v1/conversations`。它以可见普通题的展示编号和 `service_type=socratic_hint` 创建或读取本人唯一活动会话，启动服务端思考倒计时；重试不会重置时间。原三条 Agent API 路径保留，版本仍为 1.0.0；此实现稿补充没有代替跨团队签字或宣告新冻结。会话入口补充后曾为34项HTTP操作，随后H5再增加2项公开分页，当前合计36项（学习6、Agent4、导入5、知识21）。
