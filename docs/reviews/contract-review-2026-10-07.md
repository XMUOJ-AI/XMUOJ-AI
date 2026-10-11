# 知识点交付包与后端契约评审

**结论：新包的主要业务边界清楚，可以作为本轮目标需求；但 0.9.9 仍不是准确、完整、可以直接派发开发的冻结契约。** 除交付方已经列出的 4 项模型冲突和 8 项后端决策外，本次确认了 10 项需要修正或明确的契约问题。其中正常响应的 null 表达、审核详情 discriminator 已通过标准验证器复现失败；并发防环与旧导入写入规则也需要先修订。

你作为后端负责人，应先完成模型和契约评审收口，再主导六个模型、事务审核、权限和 API 实现。具体顺序、责任人及验收条件见 [任务清单](../plans/backend-task-list-2026-10-07.md)。本次没有实现功能、批准提案、冻结版本、连接数据库或执行迁移。

## 1 依据和优先关系

| 依据 | 本次用途与状态 |
| --- | --- |
| 新 ZIP `xmuoj知识点体系模块交付包.zip` | SHA-256 `584056c4fcacb778f2faeba72b832fddc266d805ed41162b9acbff04ed5ab2c1`；[展开原件](../knowledge/review-v0.9.9/README.md) 保持字节不变，README 明确仍是评审版 |
| [官方仓库快照](https://github.com/XMUOJ-AI/XMUOJ-AI/tree/144410a5a1847afa443f6ee609e13fdc256e187d) | 2026-10-07 在线核对 main/HEAD；完整 commit `144410a5a1847afa443f6ee609e13fdc256e187d`，提交日期 2026-09-09 |
| 第一期旧契约 | 当前 `docs/` 下数据模型、接口、导入、学习和 Agent 契约；提供未被新包整体替代的基线，不将“已冻结”误认为已实现 |
| [计划书](../project/大创项目计划书.md)、[需求](../project/需求文档.docx)、[技术设计](../project/技术路线与功能实现设计.docx) | 判断整个后端范围和协作边界；与新模块冲突的早期示例不能覆盖新包已确认规则 |
| [题库扩容计划](../project/题库扩容计划书.pdf)、[系统设计参考案例](../project/系统设计参考案例.pdf) | 补充数据流程和参考架构；不单独视为现行 API 定义 |

本次按用户要求，以新包确定知识点目标需求；保留其“上游模型尚待批准”的事实。产品确认 D-01～17 不等于数据库提案已合入。官方代码 commit 已知，也不等于修订后契约已有批准 commit。原包的 Windows 路径只作为历史采集记录。

## 2 实际代码到哪一步了

按旧目录与新 `backend/`、`frontend/` 重映射比较，后端 210 个原跟踪文件中 209 个字节一致，唯一不同是 Dockerfile 的目录路径。前端 146 个旧跟踪文件中 143 个一致，差异为 build.js、dev-server.js、package.json，另新增两个 Mock 文件；build.js 差异来自旧本地未提交的 `process.exit(0)`。新布局与 Mock 不代表新后端业务已经完成。

| 模块 | 已有内容 | 仍需做的内容及代码依据 |
| --- | --- | --- |
| OJ 基础 | 账号、题目、提交、比赛、判题 | 在已有业务上扩展；[Problem](../../backend/problem/models.py) L43 起、[Submission](../../backend/submission/models.py) L25 起 |
| ProblemTag 治理 | 别名、启停、排序、合并、审计，迁移 0015 | 不要重新建一套标签治理；知识点 code、先修图、映射权重和审核是不同概念。见 [tag.py](../../backend/problem/tag.py) L11～210 |
| Knowledge | 未在源码模型、迁移、注册和路由发现实现 | 六对象及全部领域服务/API 待做；见 [LOCAL_APPS](../../backend/oj/settings.py) L44 起和 [URL 注册](../../backend/oj/urls.py) |
| Session/权限 | 已有 Session、CSRF 中间件、三类账号及 OWN/ALL/NONE | 新模块需独立检查对象范围和禁止自审；[account/middleware.py](../../backend/account/middleware.py) L10～19 的 APPKEY 路径会设置 CSRF 已处理，不能直接视为新 Session 合同已满足 |
| 响应 | 旧运行时 `{error,data}` | 缺 request_id、新模块实际状态码和标准错误详情；[utils/api/api.py](../../backend/utils/api/api.py) L43～50、85～89、142～157。增加模块专用适配层，不改全站旧语义 |
| 题目导入 | 同步旧 ZIP 导入、已有离线题包构建器 | 没有新批次/来源绑定/幂等 commit/异步校验。旧 [ImportProblemAPI](../../backend/problem/views/admin.py) L744 起继承 CSRFExemptAPIView；atomic 内直接 return 错误和测试文件写入不能提供新链路所需的整体失败恢复 |
| 后台任务 | Dramatiq 判题与 Redis 队列 | 没有学习事件、Elo、导入 worker、AgentRun。见 [judge/tasks.py](../../backend/judge/tasks.py)、[判题结算](../../backend/judge/dispatcher.py) L208～244 |
| 学习、RAG、Agent、教学班 | 旧文档有设计 | 当前源码无对应业务模块，不能写成已实现。教师接口后续还需处理 `/api/admin/` 只准 Admin 的中间件边界 |

静态源码缺少知识表不证明目标数据库为空；开发/测试/生产数据库状态仍须后端核验。本次保留已有 OJ 模型、源码与迁移，没有借文件整理升级依赖或改业务逻辑。

## 3 新包已明确改变的旧规则

以下是交付包自己列出的差异，不是本次新增发现。依据 [模型提案](../knowledge/review-v0.9.9/data-model-change-proposal-v0.9.8.md) 第 2～4 节与 [差异归档](../knowledge/review-v0.9.9/backend-difference-archive-v0.9.8.md) 第 4～5 节。

| 编号 | 旧设计 | 新目标及你要确认的落地结果 |
| --- | --- | --- |
| DM-01 | 知识点默认 active | API 创建先为 draft；种子经确认后激活 |
| DM-02 | 依赖唯一键含 relation_type | 同一有向点对只允许一条正式边 |
| DM-03 | 正式依赖无 version | 增加 version，update/delete 使用 base_version 乐观锁 |
| DM-04 | 每个已发布题必须有 approved primary | 历史题可 unannotated；只对存在的当前集合要求一个 primary |
| DR-01 | 正式依赖表混有审核状态 | 正式表仅生效边；审核状态由申请持有，决定旧字段去留 |
| DR-02 | 依赖权重可为 0 | `0 < weight <= 1`，核查旧零值和数据库约束 |
| DR-03 | 正式边归属字段不同 | 明确创建/审核人、历史归属和用户删除 FK 策略 |
| DR-04 | ProblemKnowledge 逐行待审 | 候选整批保存，批准后原子替换当前 approved 集合 |
| DR-05 | 倾向全部软停用 | 允许从未引用 draft 审计后物理删除；其他情况受控禁止 |
| DR-06 | 缺三个审核/历史对象 | 新增依赖变更申请、映射批次、只追加审核事件；确定表/索引/FK/保留规则 |
| DR-07 | 无提交/批准双版本 | batch_version 每提交递增；approved_version 仅批准递增；base_version 引用后者 |
| DR-08 | 未明确禁止自审 | 提交人不能 approve 或 reject 自己申请；403 且业务和审计不变 |

此外，主站必须登录且只读；知识点目录和依赖的写操作及审核仅 Super Admin，Admin+ALL/OWN 可读取管理目录和正式图；ALL/OWN 是题目权限，不是新角色。一期不新增教师角色，不支持比赛题标注；权重不要求和为 1；图最多 500 节点；当前正式依赖/映射及 pending 引用未清理时不得废弃知识点。这些是已确认目标，不应交给开发者任意选择。

## 4 本次新增的准确性和完整性问题

这里的 P1 表示会直接阻碍正确实现或联调，P2 表示需要冻结前明确的字段/状态/查询边界。新包未实现，以下不是声称线上已经发生故障。文件行号以本次原样保留的新包为准。

### CR-01 P1 正常 null 响应被 Schema 拒绝

位置：[OpenAPI](../knowledge/review-v0.9.9/knowledge-api-v1.yaml) L1776～1782、2247～2253。`pending_batch`、`before`、`proposed`、`reviewed_by` 使用非空 `$ref` 的 allOf，外层写 nullable，无法使内层对象自动接受 null。

**已复现：** 未标注题的 `pending_batch=null`，待审 create 的 `before=null`、`reviewed_by=null` 均被 OAS30Validator 拒绝。历史题可未标注是核心兼容要求，不能靠不返回此场景解决。按 [OpenAPI 3.0.3 Schema Object 规则](https://spec.openapis.org/oas/v3.0.3.html#schema-object)，nullable 只改变同层显式 type，其他分支约束仍然有效。

建议在现有 3.0.3 内修正可空对象表达，逐个验证 allOf 分支；仅补外层 type 不能直接宣布修好。验收覆盖 unannotated、ready 无 pending、待审 create/delete 和已审核申请，并保证必需的非空对象仍被约束。

### CR-02 P1 审核详情类型判别无法解析

位置：OpenAPI L2297～2343。discriminator 只有 `propertyName: object_type`，业务值为 `dependency_change`/`problem_mapping`，实际 Schema 名却为 `DependencyChangeReviewDetail`/`ProblemMappingReviewDetail`，缺少显式 mapping。

**已复现：** 合法依赖审核详情触发 `Unresolvable JSON pointer: 'components/schemas/dependency_change'`。241 个显式 `$ref` 全可解析仍抓不到这个隐式引用问题。补两项 discriminator mapping，验证两类完整详情及错误 object_type/交叉混用反例。

### CR-03 P1 跨申请并发防环缺少充分保证

位置：[数据契约](../knowledge/review-v0.9.9/knowledge-data-contract-v1.md) L77、116、145～150；PRD L341、351、484。当前只规定事务内防环，并锁申请、目标边及涉及点，没有约定能覆盖整张图结构写入的并发协议。

反例：已有 A→B、C→D，同时批准 B→C 和 D→A。两个新边的端点锁互不冲突，各自读取旧图都无环，合并后却成环。附件仅做了确定性图模拟，**尚未运行真实数据库并发测试**。

后端需明确图写入串行化机制、锁顺序及重试语义，例如先评审单一知识图事务锁；不要把“有 transaction.atomic”视为充分证明。映射提交/批准与知识点废弃也要共享引用锁协议。验收必须用 PostgreSQL 两连接验证跨端点成环、更新/新增竞争和新增引用/废弃竞争，失败无业务或审计半成品。

### CR-04 P1 旧导入生产者仍写 pending 正式映射

位置：[旧导入契约](../problem-import-contract-v1.md) L173、200；新数据契约 L81、91、100、116。旧文明确 `knowledge_candidates` 生成待审 `ProblemKnowledge`，新包却规定该表只保存当前 approved 集合。

DR-04 已覆盖模型变化，但只改模型第 5 节不能同步导入团队的写入协议。必须一并决定候选如何进入批次或暂存区：没有 primary、未知 code、多义、已有 pending、版本冲突怎样处理，以及未来 import 来源与一期 manual 固定值的边界。不能自动批准或静默丢候选。

验收使用合法和不完整候选题包，确认正式表无 pending/rejected，既有 approved 集合不被覆盖，校验失败不破坏题目事务；文档、导入服务和数据团队输出一致。

### CR-05 P2 页面需要的字段没有完整来源

位置：PRD L454、462、548、571、593；OpenAPI L1233～1302、1743～1754、1823～1831、2203～2268；原型规格第 2.2 节。

- 探索页应从列表项更新摘要并显示前置/后继总数，PublicKnowledgePoint 没有这两个计数。根有 600 个邻居时，不能把 500 节点截断图的边数当作总数。
- 图节点需要显示分类，PublicGraphNode 没有 category 且禁止额外字段。
- 管理详情创建人、题目标注页题目摘要缺少明确的响应字段或额外请求来源。

应与前端/产品选择最少字段或明确复用现有已授权查询，不臆造字段、不误用截断计数。若产品取消展示则同步 PRD/原型，而不是由前端默默省略。

### CR-06 P2 删除后的历史标识和 before 无确定保存规则

位置：数据契约 L66～77、141；[快照 Schema](../knowledge/review-v0.9.9/knowledge-snapshot-schema-v1.json) L104～132；OpenAPI L1770～1784。

正式依赖删除后，申请的 target FK 按 SET_NULL 清空；delete 申请又不保存两端字段，但历史快照要求非空原目标 ID 和 before。接口 before 是完整 Dependency，审计快照却只保留有限关系字段。数据契约声称 before/proposed 是相同正式边结构，Schema 实际使用了不同结构。

需要定义不可变原目标身份、before/proposed 的权威保存位置和快照时点，以及历史详情怎样由受限快照生成。写审计前先取旧值只能解决当次事件，不自动定义以后的历史查询。验收执行 create→approve→update→approve→delete→approve，重启后仍能读取全部原始历史，删除不会导致 Schema 失败或 500。

### CR-07 P2 操作条件只在说明文字中约束

位置：OpenAPI L1376～1432。**已复现：** `{"operation":"create","reason":"测试"}` 缺两端等必填字段仍通过 Schema；delete 携带不适用的 proposal 字段也通过。业务文字要求服务端拒绝，因此不能据此断言后端会接受，只能确定机器定义未覆盖这些条件。

可以用三个完整 oneOf 输入分支表达 create/update/delete，或明确由服务层强制校验并交付反例；统一 400/422 分工。权重已经有 `multipleOf: 0.001`，不是本次发现的缺失字段，需验证实际 Decimal 处理与此一致。快照允许零 primary 也不单列成缺陷，因为主知识点唯一已明确交给服务层校验。

### CR-08 P2 截断摘要和正式边编辑缺少完整读取闭环

位置：OpenAPI L1360～1373、1908～1933 及 paths；数据契约 L178；PRD L313～315、339、573。管理摘要最多 100 项，只有 items/total，未定义继续获取余项的分页路径。图边有 id，但没有编辑必须的 version，也没有明确按依赖 ID 读取完整边的接口。

需按管理页面最终需求明确“更多”查询和可编辑边的 version 来源；如只提供有限摘要也须明示边界。验收使用 101 项及大图场景，任一允许维护的边都能获取正确 base_version，OWN 的 items、total 和计数同口径。不能通过取消 500 节点上限掩盖读取缺口。

### CR-09 P2 批次 payload、状态列和审计事件语义重复

位置：数据契约 L106～116、130～141；快照 Schema L184～238。payload 被要求保存完整 mapping snapshot，内部有 status/base_version/approved_version，表又有同名状态列；批准/superseded 时只描述更新状态，未明确 payload 是提交时不变快照还是同步变化。

还需确定 `replaced` 事件 2～500 字 reason 的来源：批准请求无 reason，不能让实现者随意生成。建议明确状态列权威、候选 payload 是否不可变，以及每次提交/批准/驳回/替换的事件数量、动作、版本、原因和时点。验收 v1 批准、v2 驳回、v3 替换后列、详情、审计均一致。

### CR-10 P2 跨模块引用的删除边界需补表

位置：数据契约 L34、154；旧 [data-model-v1.md](../data-model-v1.md) 的外键表及 ExternalTagMapping、StudentKnowledgeState、RatingHistory、LearningPathStep、ErrorPattern 等章节。

新模块具体删除规则只列四类引用，上游设计还存在其他知识点引用且混用 PROTECT/SET_NULL。应按真实代码和数据库列出实际引用入口，明确历史引用、软废弃及未来推荐/路径消费者如何处理。**不要求提前实现不存在的未来表**，但已部署或即将接入的生产者不能违背“从未引用 draft 才可删除”的规则。

## 5 文档收口与未决事项

- 差异归档 BE-05 仍写 `/api/knowledge/`、`/api/admin/knowledge/`；以当前 OpenAPI 的具体知识点/图谱路径为准，修订时同步。
- 差异归档末尾引用不存在的 v0.9.8 PRD，部分描述停留在 D-16，而当前已是 D-17；原件保留，问题纳入下版修订。
- README 中提到的 archive 目录未出现在本 ZIP；这是原包目录说明与实物差异，不是本次删除了历史文件。
- 审核队列默认 pending、keyword 的匹配字段、时间边界和排序并列时的次序需写成可测试规则。
- 归一化权重的舍入精度、Elo 参数、AI 自动/主动触发、向量库/模型选型是后续阶段决策，不需要借本次知识 CRUD 提前增加依赖。

响应结构复核：新知识包和保留的旧学习/Agent/导入契约均采用错误码字符串 `error`、`data={message,retryable,details}` 和 `request_id`，没有发现“一个为字符串、一个为对象”的形状冲突。真正差异是旧运行时代码未实现完整规范，以及知识草案版本 0.9.9 和旧契约版本 1.0.0 的状态不同。

## 6 实际验证及其边界

| 检查 | 实际结果 | 能说明什么 |
| --- | --- | --- |
| 原题包工具 unittest | 6/6 通过 | 保留的构建器相关行为通过已有测试 |
| 旧 validate_contracts.py | `contract validation passed` | 旧三份 OpenAPI、六份 JSON Schema、正反例及黄金 ZIP 一致性通过 |
| 新 OpenAPI 3.0.3 文档校验 | 通过 | 文档结构有效，不证明实例符合业务 |
| 新快照 Draft 2020-12 元校验 | 通过 | Schema 本身合法，不证明每条业务不变量已表达 |
| 新 OpenAPI 显式引用 | 241 个均可解析 | 不覆盖 discriminator 的隐式引用 |
| null 与审核详情反例 | 已复现拒绝/隐式引用失败 | CR-01/02 是可重现的机器契约问题 |
| 缺字段/多余字段输入 | 仍被 Schema 接受 | CR-07 需补约束或服务级负例 |
| 并发成环反例 | 单独无环、合并有环 | 设计层反例；不等于数据库并发实测 |

复现脚本、原始输出、依赖版本和命令见 [审查附件](evidence-2026-10-07/README.md)。本次未运行数据库查询、Django 服务/测试、迁移、真实 HTTP/并发、性能测试或前端构建；Word/PDF 采用文本提取核对需求，未做排版一致性验收。没有把未执行检查写成通过。

## 7 后端评审结束的具体标准

1. 核实实际数据库和环境，关闭 DM-01～04、DR-01～08。
2. 修正 CR-01/02，明确 CR-03 的并发方案和 CR-04 的导入生产者协议。
3. 对 CR-05～10 给出接受方案或明确的范围决定，同步各份定义及反例。
4. 形成可追溯的已批准模型、迁移规范、API/Schema 与源码基线；由真实负责人完成交付包所要求的冻结确认。
5. 冻结后按任务卡实施与验收；本报告和任务清单不是代签的批准记录。
