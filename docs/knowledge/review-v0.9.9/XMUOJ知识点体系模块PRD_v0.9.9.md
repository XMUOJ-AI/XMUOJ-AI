---
document: XMUOJ 知识点体系模块产品需求文档
version: 0.9.9
status: 待上游数据模型变更批准和四方评审
authority: business-requirements
updated: 2026-09-21
---

# XMUOJ 知识点体系模块产品需求文档

*适用于产品评审 前后端开发 测试验收和开发 Agent 执行*

| 项目 | 内容 |
| --- | --- |
| 文档版本 | 0.9.9 |
| 文档状态 | 待上游数据模型变更批准和四方评审 |
| 编制日期 | 2026 年 9 月 21 日 |
| 模块范围 | 管理端 CRUD 与审核 主站已登录用户只读浏览 |
| 目标系统 | 现有 XMUOJ 前后端增量扩展 |

本版本在 v0.9.8 基础上固化主站知识点探索页：`/knowledge` 同页包含局部图谱、知识点列表和当前知识点摘要；列表承担关键词、分类、层级和分页筛选；用户点击列表项后才加载以该知识点为根的局部图谱及摘要。局部图谱只控制上下游展开深度，不重复提供分类和层级筛选；完整图谱筛选仍由 `/knowledge/graph` 承担。其余已确认产品规则保持不变，开发 Agent 不得自行改变页面职责或请求触发时机。

本交付包是评审稿，不是可派发开发 Agent 的冻结包。`data-model-change-proposal-v0.9.8.md` 尚未合入上游 `data-model-v1.md`，并且源码目录没有可读取的 Git commit。完成上游合并、补录前后端 commit、安装模块级 AGENTS.md、四方评审并冻结为 1.0.0 之前，开发 Agent 必须停止，不得开始实现。

## 开发 Agent 使用规则

本文件是知识点体系模块业务需求的唯一可编辑源文件。Word 文件仅用于评审、打印和归档，不得单独修改业务规则。若需要变更需求，先修改本文件，再同步生成 Word 版本。

开发前按以下顺序读取：

1. 对应源码根目录的 `AGENTS.md`：该代码库内的修改边界、验证命令和停止条件。
2. 上游已批准的 `data-model-v1.md`，以及已合入该文件的知识模块变更。
3. [OpenAPI 契约](./knowledge-api-v1.yaml)：接口路径、方法、字段、类型、枚举和状态码。
4. [审核快照 Schema](./knowledge-snapshot-schema-v1.json)：审核快照允许的数据结构。
5. [数据契约](./knowledge-data-contract-v1.md)：数据库对象、约束、事务和迁移规则。
6. 本 PRD：业务目标、权限、流程、页面状态和验收标准。
7. [开发 Agent 任务卡](./KP-Agent开发任务卡.md)：单次任务允许修改的范围和停止条件。

交付包内提供的 `agent-baseline/backend/AGENTS.md` 和 `agent-baseline/frontend/AGENTS.md` 是待安装模板，不会自动约束其他源码目录。冻结前必须分别复制到后端和前端代码库根目录并由负责人确认。机器契约、PRD、上游模型或现有代码相互冲突时停止开发并提交契约变更，不得自行兼容；任务卡只能缩小单次实现范围。

## 1 文档结论和使用方法

本模块第一期交付管理员端的知识点目录 CRUD、依赖维护、普通题知识点映射和人工审核，以及主站已登录用户的知识点目录、详情和图谱只读浏览。主站不提供编辑表单。业务数据由数据库约束、服务层规则和人工操作共同形成；开发 Agent 只能实现确定规则，不得代替产品作出业务决定。

开发人员应按需求编号逐项实现，测试人员按验收条件编写用例。若文档与机器契约冲突，或实现必须突破禁止修改范围，应停止开发并提交问题，不得自行选择解释。

| 优先级 | 权威来源 | 适用内容 |
| --- | --- | --- |
| 1 | 已批准的上游数据模型和迁移 | 表结构 字段 约束 默认值 数据迁移 |
| 2 | 批准后的 OpenAPI 和快照 Schema | 路径 方法 字段 类型 枚举 状态码 快照 |
| 3 | 本 PRD 的业务规则和验收标准 | 产品行为 权限 流程 页面状态 |
| 4 | 页面规格和交互原型 | 布局 文案 交互顺序 |
| 5 | 开发任务卡和代码库 AGENTS.md | 单次迭代允许修改范围和验证命令 |

## 2 背景 目标和成功标准

现有 XMUOJ 已具备题目、标签、提交、比赛和基础管理能力，但管理端尚不能独立维护算法知识点、知识点之间的前置关系以及题目与知识点的映射，主站也没有知识点浏览入口。本期补齐三个管理对象，并让已登录用户在主站查看已生效数据。人工审核继续区分待处理数据与当前生效数据。

### 2.1 产品目标

- 建立可维护、可复用、可追溯的知识点目录，首批覆盖 BFS 和 DFS 相关知识。

- 建立可维护且无环的知识点前置关系，并提供图形和表格查看方式。

- 将 XMUOJ 题目绑定到一个或多个知识点，并区分主知识点、辅助知识点和前置知识点。

- 通过人工审核保证普通查询只返回当前生效的映射和依赖。

- 已登录学生和管理员从主站“知识点”进入相同的只读目录；管理员需要维护时跳转现有管理员端，不在主站复制 CRUD。

- 在不升级旧框架、不改写现有题目标签和历史提交的前提下完成增量接入。

### 2.2 第一期成功标准

| 编号 | 指标 | 验收口径 |
| --- | --- | --- |
| S1 | 知识点可管理 | Super Admin 可完成创建 查询 编辑 启用和受控废弃；非法字段由前后端共同拒绝 |
| S2 | 依赖图正确 | 任何写操作均不能产生自环 重复边或多节点环 |
| S3 | 题目可标注 | 题目可绑定 1 至 20 个知识点；当前生效的映射集合必须有且仅有一个审核通过的主知识点 |
| S4 | 审核边界生效 | 普通查询不得把 pending 或 rejected 数据作为当前生效数据返回 |
| S5 | 兼容旧系统 | 现有题目 提交 比赛 判题和标签回归测试通过，历史数据不被批量改写 |
| S6 | 可自动验收 | OpenAPI 可解析，核心业务规则均有正例和反例测试 |
| S7 | 主站可浏览 | 已登录用户可从主站导航进入知识点列表、详情和图谱；主站没有知识点、依赖或映射写操作 |
| S8 | 学生数据隔离 | 主站只返回 active 知识点、正式依赖及 visible=true 且 contest 为空的普通题 approved 映射；匿名请求为 401 |

## 3 范围

### 3.1 本期范围

- 知识点列表、详情、新建、编辑、状态变更和条件筛选。

- 知识点前置依赖的查询、新增、受控变更、删除、审核和防环校验。

- 普通题目的知识点映射查询、提交、审核通过和驳回。

- 管理员侧知识图谱查看；默认提供筛选、定位和只读浏览，编辑通过受控表单完成。

- 主站增加仅登录后可见的“知识点”导航入口及列表、详情、图谱三个只读页面。

- 主站采用独立只读接口，仅暴露已生效数据；管理员维护操作仍使用现有 `/admin/` 页面与管理 API。

- 现有管理端路由、菜单、Session、CSRF、错误包络和权限体系的增量接入。

- 首批 BFS、DFS 知识点种子清单的人工确认和导入。

### 3.2 明确不在本期

- 不向未登录用户开放知识点页面或接口；不提供学生侧编辑、学习进度、自动推荐或其他智能化业务能力。

- 不实现任何自动生成、自动审核、自动调整或自动发布业务数据的功能。

- 不实现课程班级和独立教师角色；一期复用现有 AdminType 与 ProblemPermission。

- 不支持比赛题知识点标注；contest 非空的 Problem 在一期返回功能未开放。

- 不引入 Neo4j 等图数据库，依赖图使用关系表和领域服务实现。

- 不升级 Vue 2、Webpack 3、Element UI、Django 或数据库主版本。

- 不重构判题、比赛、提交、登录、题目标签和导入模块。

## 4 用户 角色和权限

一期没有独立教师角色，复用现有 AdminType 与 ProblemPermission。ALL、OWN、NONE 是 ProblemPermission 的枚举值，用于限定普通 Admin 可操作的题目范围，不是三个独立管理员角色，也不授予知识体系维护或审核权限。知识点目录、依赖关系和审核的写操作仅允许 Super Admin。

下表只描述管理员端权限，不得将管理员端的查看权限当作主站浏览条件。已登录的 Regular User 和 Admin+ProblemPermission.NONE 都可以查看主站已生效数据，但不能因此访问管理员端。

| 身份与题目权限组合 | 知识点目录 | 依赖关系 | 题目标注 | 审核 |
| --- | --- | --- | --- | --- |
| Super Admin | 全部 | 全部 | 全部普通题 | 允许 |
| Admin + ProblemPermission.ALL | 查看 | 只读 | 全部普通题 | 不允许 |
| Admin + ProblemPermission.OWN | 查看 | 只读 | 仅本人创建的普通题 | 不允许 |
| Admin + ProblemPermission.NONE | 不可访问 | 不可访问 | 不可访问 | 不允许 |
| Regular User | 不可访问管理端 | 不可访问 | 不可访问 | 不允许 |

对象权限规则：Super Admin 可标注全部普通题；ProblemPermission.ALL 可标注全部普通题；ProblemPermission.OWN 只能标注 created_by 为当前用户且 contest 为空的题目。Admin 的 ProblemPermission 不得用于推导知识点、依赖关系或审核写权限。无权访问的题目对象统一返回 404，避免泄露对象是否存在；无模块功能权限返回 403。

| 主站身份 | 目录 详情 图谱 | CRUD 标注 审核 | 未生效对象 |
| --- | --- | --- | --- |
| 未登录 | 不允许；页面进入登录流程，接口返回 401 | 不允许 | 不返回数据 |
| 已登录 Regular User | 已生效数据只读 | 不允许 | 详情返回 404 |
| 已登录 Super Admin | 已生效数据只读 | 可跳转 `/admin/knowledge`；管理端按上表授权 | 详情返回 404 |
| 已登录 Admin+ALL/OWN | 已生效数据只读 | 可跳转现有 `/admin/problems`；仅标注有权普通题 | 详情返回 404 |
| 已登录 Admin+NONE | 已生效数据只读 | 无知识模块管理跳转 | 详情返回 404 |

主站统一只读数据规则：知识点仅 `status=active`；依赖只从正式 `KnowledgeDependency` 查询且两端知识点均 active；题目关联仅来自当前 approved 映射集合，且 Problem 满足 `contest_id__isnull=True, visible=True`。这个题目过滤条件与现有 OJ 普通题列表和详情保持一致。主站不得返回 draft、deprecated、pending、rejected、审核快照、审计事件或不可见题目的题号及标题。管理账号在主站浏览时也使用同一过滤视图，需要查看待审数据时进入管理员端。权限过滤必须在后端查询与序列化时完成，隐藏按钮不等于授权。

## 5 名词和数据语义

| 名词 | 定义 |
| --- | --- |
| 知识点 | 稳定、可复用的算法或基础能力单元，以 code 作为对外机器标识。 |
| 前置知识点 | 学习 dependent 前应先掌握的 prerequisite。 |
| 必需依赖 | relation_type=required，表示后继知识点以该前置知识点为必要基础。 |
| 推荐依赖 | relation_type=recommended，表示该前置关系可选；本期只保存和展示，不执行自动计算。 |
| 主知识点 | 题目主要考查的知识点；一期每个已生效映射集合恰好一个 approved primary。 |
| 辅助知识点 | 题目同时涉及但非主要考查目标的知识点。 |
| 前置映射 | 完成题目之前建议已掌握的知识点，不等同于依赖图中的边。 |
| 权重 | 大于 0 且小于等于 1 的相对重要程度；各映射权重不要求求和为 1，消费方需确定性归一化。 |
| 覆盖状态 | unannotated 未标注，in_review 有待审核批次，ready 已有生效映射；历史题默认 unannotated，不阻断原有发布和判题。 |
| 审核状态 | pending 待审核，approved 已通过，rejected 已驳回。主站只把 approved 且两端 active 的依赖、当前 approved 且题目可见的映射视为生效数据。 |
| 依赖变更申请 | 对知识依赖执行 create、update 或 delete 的独立审核对象。申请未批准时不改变正式依赖。 |
| 批次版本 | batch_version；同一题目每提交一次映射批次加 1，驳回也占用版本。 |
| 批准版本 | approved_version；只有映射批次批准时加 1，用于当前生效集合和乐观锁。 |

## 6 现有系统接入约束

- 后端保留现有 Problem、Submission、User 主键和表语义，通过扩展表建立外键。

- 普通题对外展示编号仍使用 Problem._id；知识模块内部引用使用 Problem 主键。

- 新增 API 继续使用 Django Session Cookie；所有写请求必须校验 X-CSRFToken。

- 知识模块新接口使用专用后端 `KnowledgeAPIView` 响应基类和前端 `knowledgeRequest` 适配器，统一返回 error、data、request_id 包络与 X-API-Version。不得修改现有全局 APIView、JSONResponse 或 ajax 的响应语义。204 响应没有 JSON body，由适配器直接解析为空结果。

- 主站只读页复用现有 OJ 前端路由、导航和登录态；CRUD 与审核页继续使用管理端 history 路由和 `/admin/` base，不引入新路由库或状态管理方案。

- 初始迁移只创建新表和必要索引，不批量修改 Problem.tags、Problem.difficulty 或历史提交。

| 层级 | 建议接入点 | 允许的最小改动 |
| --- | --- | --- |
| 后端 URL | oj/urls.py | 分别增加 knowledge.urls.public 和 knowledge.urls.admin 的 include；主站接口只读且登录校验独立 |
| 后端模块 | 新增 knowledge Django app | 模型 服务 API 序列化器 URL 测试 |
| 题目模块 | problem 只作为被引用对象 | 禁止向 Problem 表直接新增知识点 JSON 字段 |
| 管理端路由 | src/pages/admin/router.js | 增加知识点相关子路由 |
| 管理端页面 | src/pages/admin/views/knowledge | 新增隔离目录及导出 |
| 侧栏菜单 | src/pages/admin/components/SideMenu.vue | 在题目管理区域增加知识点入口 |
| API 封装 | 新增知识模块专用 request 与 API 文件，现有 admin api 仅做导出接入 | 使用 knowledgeRequest 解析新包络；不得修改全局 ajax |
| 主站路由和页面 | src/pages/oj/router/index.js 及独立 knowledge 页面目录 | 增加列表 详情 图谱三页，不改旧题目页面语义 |
| 主站导航和 API | 现有 OJ 导航与请求封装 | 登录后显示知识点入口；增加专用只读请求方法 |

## 7 信息架构和路由

主站“知识点”只在用户登录后显示，所有已登录身份都从此进入只读列表。未登录用户即使直接输入路由，也应进入现有登录流程，登录后返回目标页面。管理员端维持独立的管理路由和权限；主站不放新建、编辑、状态变更、依赖维护、题目标注或审核表单。Super Admin 从主站“管理知识点”进入 `/admin/knowledge`；Admin+ALL/OWN 从“前往题目管理”进入现有 `/admin/problems`，再按题目权限进入标注页。Admin+NONE 和 Regular User 没有管理跳转。跳转按钮依据现有已认证身份显示，目标管理 API 再次授权，不能由主站浏览权推导。

| 主站路由 | 页面 | 核心动作 | 权限 |
| --- | --- | --- | --- |
| /knowledge | 知识点探索 | 筛选列表 选择知识点 查看局部图谱和摘要 进入详情或完整图谱 | 已登录用户只读 |
| /knowledge/graph | 完整知识图谱 | 搜索 筛选 定位 查看已批准依赖 | 已登录用户只读 |
| /knowledge/:code | 知识点详情 | 查看定义 前置 后继及可见普通题 | 已登录用户只读；非 active 为 404 |

主站静态路由 `/knowledge/graph` 必须在 `/knowledge/:code` 前声明。三个页面只调用主站只读 API，不调用管理员端 GET 接口；后者可以含内部或待审核字段。

| 路由 | 页面 | 入口 | 核心动作 | 权限 |
| --- | --- | --- | --- | --- |
| /admin/knowledge | 知识点列表 | 题目管理侧栏 | 筛选 查看 新建 编辑 废弃 | 按角色矩阵 |
| /admin/knowledge/:code | 知识点详情 | 列表名称或查看按钮 | 查看基本信息 依赖 关联题目 | 可查看者 |
| /admin/knowledge/graph | 知识图谱 | 知识点列表页 | 筛选 定位 查看关系 | 可查看者 |
| /admin/problem/:problemId/knowledge | 题目标注 | 题目列表与编辑页 | 设置角色 权重 提交 | 题目管理权限 |
| /admin/knowledge/reviews | 知识审核 | 题目管理侧栏 | 查看差异 通过 驳回 | 仅 Super Admin |

路由顺序要求：/admin/knowledge/graph 和 /admin/knowledge/reviews 必须在 /admin/knowledge/:code 之前声明，避免被动态参数路由吞并。

## 8 核心流程

### 8.1 知识点建立流程

1. Super Admin 新建 draft 知识点并填写 code、名称、描述、分类和层级。

1. 系统执行字段校验、code 唯一校验和 normalized_name 唯一校验。

1. Super Admin 补充别名和课程章节元数据后，将状态改为 active。

1. active 知识点可被依赖关系和题目标注引用。

1. 仅从未被依赖、依赖变更申请、题目映射或映射批次引用的 draft 知识点可由 Super Admin 受控删除；active/deprecated 不提供物理删除。如需废弃 active，先处理其 pending 依赖变更申请和映射批次，通过变更申请删除或替换当前正式依赖，再改为 deprecated。历史审核与已替换批次保留。

### 8.2 依赖关系流程

1. Super Admin 选择 create、update 或 delete，并填写目标依赖、拟变更内容和原因。

1. 服务锁定相关对象，校验端点状态、目标 version、重复申请和基础字段，并创建 pending `KnowledgeDependencyChangeRequest`；正式 `KnowledgeDependency` 不改变。

1. Super Admin 在审核详情中查看当前关系、拟变更内容和影响。审核通过时，服务在同一事务再次检查唯一性和环；create 创建正式边，update 原子更新并递增 version，delete 删除正式边。

1. 申请驳回不改变正式依赖。update 或 delete 等待审核期间，旧 approved 边继续在管理员端默认图和主站图中生效。

### 8.3 题目标注流程

1. 题目管理人员从普通题列表或编辑页进入题目标注页。

1. 选择一个主知识点，可选多个辅助或前置知识点，并设置每项权重。

1. 前端先校验，后端在事务中执行同样规则并创建 pending KnowledgeMappingBatch；batch_version 每次提交加 1，base_version 等于提交者看到的 approved_version；当前 approved ProblemKnowledge 不变。

1. Super Admin 查看题目摘要和映射列表，选择通过或填写驳回原因。

1. 审核通过后，新映射集合成为普通查询返回的当前生效集合，approved_version 加 1；驳回只消耗 batch_version，不增加 approved_version。

## 9 功能需求

### 9.1 知识点管理

#### KP-FR-001  查询知识点列表

- **角色**：有知识模块查看权限的管理账号

- **输入**：关键词、category、level、status、页码和每页数量

- **规则**：关键词匹配 code、name、normalized_name 和 aliases；默认按 updated_time 倒序；每页 20，最大 100

- **输出**：code、name、category、level、status、版本、关联题目数、前置和后继数量、更新时间

- **验收**：无数据返回 HTTP 200 和空 items；筛选条件在刷新后可从 URL 恢复。

#### KP-FR-002  创建知识点

- **角色**：Super Admin

- **输入**：code、name、description、category、level、aliases、metadata

- **规则**：code 创建后不可修改；初始 status=draft、version=1；code 与 normalized_name 全局唯一

- **名称规范化**：NFKC 后去首尾空白、连续 Unicode 空白折叠为单个空格、仅 ASCII A-Z 转小写；保留中文 数字和标点

- **异常**：重复 code 或规范化名称返回 409；非法字段返回 400

- **验收**：合法数据创建成功返回 201；重复提交不得生成两条记录。

#### KP-FR-003  编辑知识点

- **角色**：Super Admin

- **输入**：除 code 外的可编辑字段及当前 version

- **规则**：使用乐观锁；任一可编辑字段修改成功后 version 加 1；并发冲突返回 409

- **限制**：deprecated 知识点仅允许补充描述和别名，不允许恢复为 draft

- **验收**：两个客户端使用同一旧版本保存时，只有一个成功，另一个收到版本冲突且数据不被覆盖。

#### KP-FR-004  变更知识点状态

- **角色**：Super Admin

- **状态机**：draft 可转 active；active 可转 deprecated；deprecated 默认不可恢复

- **规则**：draft 不可被 approved 映射引用。active 转 deprecated 前，必须不存在引用该点的 pending 依赖变更申请或待审映射批次，也不存在当前正式依赖和 `ProblemKnowledge` 映射；先在管理端完成审核、通过变更申请删除依赖或提交替换映射。deprecated 不可新增引用，但保留已替换批次、审核事件等历史记录

- **验收**：状态非法跳转或仍有当前生效/待审引用时返回 409，原状态和版本不变；清理当前引用后允许废弃；历史审核与已替换批次仍可在管理端查询，主站不显示 deprecated。

#### KP-FR-005  删除未使用草稿知识点

- **角色**：仅 Super Admin。
- **输入**：knowledge_code、当前 version 和 2 至 500 字删除原因，以管理端 POST 删除命令的 JSON 请求体提交；必须先二次确认。不要把中文原因塞入 HTTP Header 或 URL query。
- **规则**：只允许删除 status=draft 且从未被任何正式依赖、依赖变更申请、`ProblemKnowledge` 行、待审或历史映射批次引用的知识点；active/deprecated 即使当前无引用也返回 409。服务端在同一事务锁定知识点、再次检查版本及全部引用、写入 `KnowledgeReviewEvent` 的 knowledge_point/deleted 事件和受限前后快照，再物理删除。事件 object_key 使用 code、object_version 使用删除前 version，前快照只含 code、name、category、level、status、version，后快照为 null；审计不记录 metadata 或描述全文。
- **验收**：合法草稿删除返回 204；原因缺失返回 400，版本不一致或状态/引用不允许时返回 409，知识点与审计均不改变；不能通过该接口绕过 active 废弃流程。

#### KP-FR-006  查询管理端知识点详情

- **角色**：有知识模块查看权限的管理账号

- **输出**：知识点全部管理字段、capabilities、前置和后继摘要、关联题目摘要；三类摘要分别稳定排序并限制数量，响应给出总数

- **规则**：依赖摘要只返回当前正式依赖；题目摘要按调用者的题目对象权限过滤。列表中的前置数、后继数和关联题目数必须与详情使用同一查询口径。实现必须使用聚合、prefetch 或批量查询，禁止逐行查询造成 N+1

- **验收**：详情页首屏不需要调用列表接口拼装；不同角色的 capabilities 与后端授权一致；查询数不会随摘要条数线性增长。

### 9.2 依赖关系管理

#### KD-FR-001  查看依赖图

- **角色**：Super Admin，或 Admin+ProblemPermission.ALL/OWN；普通 Admin 只能查看正式依赖，不查看变更申请

- **输入**：category、level、root_code、depth；depth 默认 3、上限 8

- **规则**：正式图仅包含 active 知识点和正式依赖。指定 root_code 时先在未应用 category/level 的正式图中，从根节点同时沿 prerequisite 上游和 dependent 下游遍历；根节点距离为 0，一条边距离为 1，遍历至 depth。然后对非根节点应用 category/level，根节点始终保留。root_code 不存在或非 active 时返回 404。未指定 root_code 时 category/level 过滤全部 active 节点，depth 被忽略

- **截断**：候选节点超过 500 时按 `(distance, code)` 取前 500 个；无 root 时距离统一为 0，等价于按 code 取前 500 个。边只保留两端均在返回节点中的正式边，并按 `(from, to)` 排序，禁止悬空边

- **输出**：nodes、edges 和 truncated；前端从 URL query 恢复筛选条件，不要求接口回显筛选对象

- **验收**：空图返回 HTTP 200；同一筛选条件下节点和边顺序稳定，便于前端复现。

#### KD-FR-002  提交依赖变更申请

- **角色**：仅 Super Admin

- **输入**：operation=create/update/delete、target_dependency_id、base_version、拟提交的 prerequisite_code、dependent_code、relation_type、weight，以及 2 至 500 字 reason。create 不传 target_dependency_id 和 base_version；delete 不传拟提交字段

- **规则**：两个知识点必须 active；同一有向知识点对只允许一条正式边；weight >0 且 <=1。create 必须不存在同向正式边或同内容 pending 申请；update/delete 必须引用当前正式边及其 version，同一目标依赖最多一个 pending 申请。提交阶段执行快速防环校验，批准阶段必须在事务内重新校验

- **验收**：申请成功返回 201 和 request_id；正式图不变。已有 A→B、B→C 时提交 create C→A 返回 422 KNOWLEDGE_DEPENDENCY_CYCLE，申请和正式边均不写入。

#### KD-FR-003  审核依赖变更申请

- **角色**：仅 Super Admin

- **动作**：approve 或 reject；reject 必须填写 2 至 500 字原因

- **规则**：提交人不得审核自己的申请。审核服务先校验当前用户不是 submitted_by；相同时返回 403 `KNOWLEDGE_SELF_REVIEW_FORBIDDEN`，申请、正式边和审计均不改变。通过身份校验后锁定申请和目标正式边，再次执行端点 active、base_version、唯一性和防环校验；非 pending 状态不可重复审核。批准 create/update/delete 后分别创建、更新或删除正式依赖，并在同一事务写审核事件

- **验收**：提交人本人尝试 approve 或 reject 均返回 403；其他 Super Admin 可正常审核。重复审核或目标版本变化返回 409；create 批准后普通图可见，update/delete 批准前旧边持续可见、批准后一次性切换；驳回不改变正式图。

#### KD-FR-004  已批准依赖的生效边界

- **角色**：仅 Super Admin。已批准依赖不能直接变更或删除，必须提交 `KnowledgeDependencyChangeRequest`

- **规则**：正式 `KnowledgeDependency` 只保存当前生效边，pending 申请独立保存，不占用正式边唯一键。update/delete 审核前旧边继续生效；批准时原子修改正式边并写前后快照。任何管理 API 都不得提供绕过审核的直接 PATCH 或删除命令

- **验收**：update/delete 申请 pending 或 rejected 时管理员端默认图和主站图仍返回旧边；批准成功后两端同时看到新状态；原因缺失、版本冲突或防环失败时正式边不变。

### 9.3 题目知识点映射

#### PK-FR-001  查看题目标注

- **角色**：对目标题目具有查看或管理权限的管理账号

- **范围**：一期只支持 contest 为空的普通题

- **输出**：题目摘要、coverage_status、approved_version、next_batch_version、当前 approved 映射、待审核批次和可执行动作

- **验收**：历史题无映射时返回 coverage_status=unannotated、approved_version=0 和空 mappings；不阻断原有发布、展示和判题；无对象权限时返回 404。

#### PK-FR-002  提交题目标注

- **角色**：Super Admin，或 Admin+ProblemPermission.ALL，或 Admin+ProblemPermission.OWN 且题目 created_by 为本人

- **输入**：base_version 和 1 至 20 条映射，每条包含 knowledge_code、role、weight

- **规则**：知识点不得重复；必须且只能有一个 primary；权重 >0 且 <=1；知识点必须 active

- **事务**：提交只创建一个 KnowledgeMappingBatch 快照，不改写当前 approved ProblemKnowledge；同题最多一个 pending 批次。batch_version 为该题历史最大 batch_version 加 1，包含 rejected 和 superseded 批次

- **验收**：任何一条非法时不创建批次；base_version 过期或已有 pending 批次返回 409；合法提交返回 review_batch_id 和 batch_version。

#### PK-FR-003  审核题目标注

- **角色**：仅 Super Admin

- **动作**：按 review_batch_id 对 pending 映射批次整体通过或整体驳回

- **规则**：提交人不得审核自己的映射批次。提交人本人调用 approve 或 reject 时返回 403 `KNOWLEDGE_SELF_REVIEW_FORBIDDEN`，批次和当前 approved 集合均不改变；其他 Super Admin 通过前重新校验 base_version 和恰好一个 primary；驳回必须填写原因

- **验收**：提交人本人不能通过或驳回该批次；其他 Super Admin 通过时在同一事务替换 ProblemKnowledge 当前集合，将本批次 approved_version 设为当前值加 1；驳回不影响旧 approved 集合且批次 approved_version 保持 null。

#### PK-FR-004  修改已审核标注

- **处理**：普通标注人员基于当前 approved_version 提交新批次；审核前普通查询继续返回旧 approved 集合

- **并发**：审批时若批次 base_version 已不是当前 approved_version，返回 409 并要求重新提交

- **验收**：替换失败时旧 approved 集合完整保留；替换成功后普通查询不存在中间状态。

版本示例：题目首次提交 batch_version=1 并批准后 approved_version=1；第二次提交 batch_version=2 后被驳回，approved_version 仍为 1；第三次提交 batch_version=3 并批准后 approved_version=2。客户端始终以 approved_version 作为 base_version，不得把 batch_version 当作乐观锁版本。

### 9.4 审核队列

#### RV-FR-001  查看审核队列

- **角色**：仅 Super Admin

- **筛选**：object_type、submitter_id、status、updated_from、updated_to、keyword。object_type 只允许 dependency_change 和 problem_mapping；时间范围使用 ISO 8601，updated_from 不得晚于 updated_to

- **排序**：默认按 created_time 正序，最早提交优先

- **输出**：列表只返回审核摘要、提交人摘要、目标摘要、operation、状态和时间，不返回完整 payload

- **验收**：分页结果稳定；筛选可从 URL 恢复；已被其他审核者处理的记录刷新后从 pending 队列移除；列表查询不得产生 N+1。

#### RV-FR-003  查看审核详情

- **角色**：仅 Super Admin

- **输入**：object_type 与 object_key

- **输出**：dependency_change 返回当前正式边、拟变更内容、base_version、原因、提交人与审核状态；problem_mapping 返回题目摘要、batch_version、base_version、当前 approved_version 和完整 mappings；两类详情都返回 capabilities，当前用户是提交人时不包含 approve 或 reject

- **规则**：详情响应以 object_type 作为判别字段；对象不存在返回 404。批准和驳回页面只使用详情接口，不从列表摘要推断完整对象。前端按 capabilities 隐藏自审操作，后端仍必须独立校验 submitted_by

- **验收**：列表响应不含完整映射 payload；进入详情后可完整复核；并发审核后重新打开详情反映最新状态。

#### RV-FR-002  审核并发控制

- **规则**：审核请求携带当前 updated_time 或版本标识；只允许 pending 转 approved 或 rejected

- **异常**：状态已变化返回 409，并要求前端刷新，不允许覆盖其他审核者结果

- **验收**：两名审核者同时操作同一记录时只有第一个成功。

### 9.5 主站只读浏览

#### SP-FR-001  登录后显示共同入口

- **角色**：已登录 Regular User 和所有管理账号；未登录用户不可浏览。
- **规则**：登录后主站导航显示“知识点”，点击进入 `/knowledge`。直接访问主站知识点路由但 Session 无效时，进入现有登录流程；三个主站 API 均返回 401 包络且不返回业务数据。不得为了本模块改变全站登录规则。
- **验收**：登录、退出登录和 Session 失效后导航及页面状态正确；匿名用户无法通过直接请求获取知识点目录或图谱。

#### SP-FR-002  浏览目录和详情

- **角色**：已登录用户，只读。
- **输入**：列表 keyword、category、level、page、page_size；详情 knowledge_code。主站不接受 `status` 参数，也不提供草稿筛选。
- **规则**：列表和详情均只返回 active 知识点。关键词沿用 KP-FR-001 的匹配范围；列表默认按 code 升序、分页默认 20、最大 100，详情非 active 或 code 不存在均返回 404。展示内容为 code、name、category、level、description、aliases 与已批准关系摘要；前置和后继摘要按对方 code 升序。更新时间、内部版本、创建人、审核人和审核状态不出现在主站响应中。
- **探索页交互**：首次进入 `/knowledge` 时只查询列表，不自动选择第一项，也不请求局部图谱；图谱区和摘要区显示“请选择知识点”。点击列表行后，将该项设为当前知识点，使用列表响应中的公开字段更新摘要，并请求 `GET /api/knowledge-graph?root_code={code}&depth={depth}`。选中行为不修改浏览器路由；只有“查看完整详情”进入 `/knowledge/:code`，“打开完整图谱”进入 `/knowledge/graph`。
- **筛选职责**：keyword、category、level、page、page_size 只属于知识点列表并写入 `/knowledge` 的 URL query。改变列表筛选或分页只刷新列表，不清空或替换当前知识点、局部图谱和摘要；即使当前项不在新的列表结果中，也继续显示，直到用户点击另一项、退出登录或页面离开。图谱区域不得复制关键词、分类或层级筛选。
- **验收**：空列表返回 200 与空 items；列表筛选写入 URL，刷新和后退可恢复；请求 draft 或 deprecated code 无法获取详情。

#### SP-FR-003  浏览已生效图谱

- **角色**：已登录用户，只读。
- **规则**：只显示 active 节点和正式依赖，两端节点都必须 active；根节点、双向遍历、先遍历后过滤、根节点保留、深度和截断规则完全沿用 KD-FR-001。指定 root_code 不存在或非 active 时返回 404；未指定根节点时 depth 被忽略。待审申请、驳回申请和废弃数据不进入返回集合。超限时返回 truncated=true 且不返回悬空边；图形不是唯一浏览方式，仍提供关系表格。
- **页面调用边界**：`/knowledge` 的局部图谱请求必须同时携带当前 `root_code` 与 depth，且不得携带 category 或 level；局部图谱中的分类与层级只作为节点属性展示。`/knowledge/graph` 可以使用 root_code、depth、category、level，并将其筛选状态写入本页 URL query；该页的节点搜索用于定位或选择根节点，不承担 `/knowledge` 列表筛选职责。
- **验收**：同条件返回顺序稳定；空图 200；点击节点进入主站知识点详情；匿名请求 401。

#### SP-FR-004  查看可见关联题目

- **角色**：已登录用户，只读。
- **规则**：知识点详情的关联题目仅从当前 approved 映射集合查询，并过滤 `Problem.contest_id__isnull=True` 与 `Problem.visible=True`；题号使用 `Problem._id`，按题号升序稳定排序，链接进入现有普通题详情。隐藏题、比赛题、pending 或 rejected 映射的题号、标题和计数均不得进入主站响应；管理端详情仍沿用原权限显示内部信息。
- **验收**：同一知识点同时关联公开普通题、隐藏题、比赛题和待审标注时，主站只展示公开普通题；点击题目链接不绕过现有题目访问规则。

#### SP-FR-005  管理跳转与双重授权

- **角色**：主站已登录管理账号。
- **规则**：Super Admin 看到“管理知识点”并跳转 `/admin/knowledge`；Admin+ALL/OWN 看到“前往题目管理”并跳转现有 `/admin/problems`，再从有权普通题进入标注页；Admin+NONE 和 Regular User 无管理跳转。主站不新增任何保存、删除或审核按钮；管理员端页面和 API 按第 4 节再次校验权限。
- **验收**：不同管理角色跳转目标正确；Regular User 与 Admin+NONE 手工访问管理员端知识页面或写 API 时被后端拒绝；OWN 访问他人题目标注仍返回 404。前端隐藏按钮不能成为唯一防线。

## 10 业务不变量

| 编号 | 不变量 | 强制位置 |
| --- | --- | --- |
| INV-01 | knowledge_point.code 全局唯一且创建后不可修改 | 数据库唯一约束 服务层 前端 |
| INV-02 | normalized_name 全局唯一 | 数据库唯一约束 服务层 |
| INV-03 | level 必须为 1 至 5 | 数据库检查 OpenAPI 前端 |
| INV-04 | 知识依赖图不得出现自环或多节点环 | 数据库自环检查 领域服务事务防环 |
| INV-05 | 同一 prerequisite 和 dependent 有向对只能存在一条边，不得以不同 relation_type 重复 | 数据库唯一约束 |
| INV-06 | 每个已生效题目映射集合必须有且仅有一个 approved primary；未标注历史题不受此约束 | 领域服务和验收测试 |
| INV-07 | 每题同一知识点只能映射一次 | 数据库唯一约束 |
| INV-08 | 普通查询不得把 pending 或 rejected 数据作为当前生效数据返回 | 领域查询服务和接口测试 |
| INV-09 | 已引用知识点不得物理删除 | 外键 PROTECT 服务层 |
| INV-10 | 批量写入整体成功或整体回滚 | 数据库事务 |
| INV-11 | 同一题目最多一个 pending 映射批次；批次必须引用创建时的 base_version | 数据库部分唯一约束和领域服务 |
| INV-12 | active 知识点仍有 pending 依赖变更申请、待审映射批次、当前正式依赖或当前 ProblemKnowledge 映射时不得 deprecated | 领域状态服务和接口测试 |
| INV-13 | 只有从未被任何业务引用的 draft 知识点可以物理删除，且删除必须有原因、版本校验和受限快照审计 | 领域服务事务、数据库引用约束和接口测试 |
| INV-14 | 正式 KnowledgeDependency 只保存当前生效边；所有 create/update/delete 必须先创建独立 pending 变更申请 | 数据库约束 领域服务 API |
| INV-15 | 同一正式依赖最多一个 pending update/delete 申请；申请批准前正式边保持不变 | 数据库部分唯一约束 事务测试 |
| INV-16 | batch_version 每次提交递增；approved_version 只在批准时递增；base_version 只引用 approved_version | 数据库唯一约束 审核服务 接口测试 |
| INV-17 | 有根图先双向遍历后过滤且始终保留根；截断按 distance、code，边不得悬空 | 图查询服务 契约测试 |

## 11 数据契约摘要

现有冻结 `data-model-v1.md` 第 5 节与本需求在知识点默认状态、依赖唯一键、依赖版本和历史题标注规则上冲突。本交付包不再声称直接沿用该模型。`data-model-change-proposal-v0.9.8.md` 提出完整修订；提案合入上游前，本节只描述目标模型，不能作为迁移授权。

| 对象 | 关键字段 | 关键约束 |
| --- | --- | --- |
| KnowledgePoint | code name normalized_name description category level status version aliases metadata | code 与 normalized_name 唯一；level 1 至 5；引用后仅可 deprecated |
| KnowledgeDependency | prerequisite dependent relation_type weight source confidence version created_by updated_time | 只保存当前生效边；有向对唯一；禁止自环和多节点环 |
| KnowledgeDependencyChangeRequest | id operation target_dependency base_version prerequisite dependent relation_type weight status reason submitted_by reviewed_by | 所有 create/update/delete 的审核对象；同一目标最多一个 pending |
| ProblemKnowledge | problem knowledge_point role weight review_status reviewed_by | 只保存当前生效集合；题目和知识点唯一；生效集合恰好一个 approved primary |
| KnowledgeMappingBatch | id problem batch_version base_version approved_version status payload submitted_by reviewed_by updated_time | 同题 batch_version 唯一；同题最多一个 pending；approved_version 仅批准时赋值 |
| KnowledgeReviewEvent | object_type object_key object_version action reason actor snapshot request_id created_time | 只追加不修改；knowledge_point 删除用 code、映射用批次 UUID 作为 object_key；快照符合 JSON Schema |

## 12 API 契约

机器可读定义见随附 knowledge-api-v1.yaml。本版已同步依赖变更申请、双版本、双向图谱、管理详情、审核详情和专用响应兼容规则。该文件仍是待评审草案；上游数据模型提案合入且产品、后端、前端和测试确认后，方可冻结为 1.0.0 并派发开发 Agent。

| 方法 | 主站路径 | 认证与数据边界 |
| --- | --- | --- |
| GET | /api/knowledge-points | Session 必需；仅 active，分页默认 20 上限 100 |
| GET | /api/knowledge-points/{knowledge_code} | Session 必需；仅 active；非 active 与不存在统一 404；关联题只取 approved 且普通题可见 |
| GET | /api/knowledge-graph | Session 必需；仅 active 节点和正式依赖；节点最多 500 |

主站路径下不定义 POST、PUT、PATCH、DELETE。所有管理写请求仍走 `/api/admin/`，由后端按原管理员权限校验。主站响应不得直接复用管理端详情序列化器，避免带出审核状态、版本、草稿、审计字段或不可见题目。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/admin/knowledge-points | 查询知识点列表 |
| POST | /api/admin/knowledge-points | 创建知识点 |
| GET | /api/admin/knowledge-points/{knowledge_code} | 查看知识点详情 |
| PATCH | /api/admin/knowledge-points/{knowledge_code} | 编辑知识点或变更状态 |
| POST | /api/admin/knowledge-points/{knowledge_code}/delete | 仅删除未引用 draft 的操作命令；JSON 体含 version、原因与审计 |
| GET | /api/admin/knowledge-graph | 查询依赖图 |
| POST | /api/admin/knowledge-dependency-change-requests | 提交依赖 create/update/delete 变更申请；正式边暂不改变 |
| GET | /api/admin/problems/{problem_id}/knowledge-mappings | 查询题目标注 |
| PUT | /api/admin/problems/{problem_id}/knowledge-mappings | 整体提交题目标注 |
| GET | /api/admin/knowledge-reviews | 查询审核队列 |
| GET | /api/admin/knowledge-reviews/{object_type}/{object_key} | 查询完整审核详情 |
| POST | /api/admin/knowledge-reviews/{object_type}/{object_key}/approve | 审核通过 |
| POST | /api/admin/knowledge-reviews/{object_type}/{object_key}/reject | 审核驳回 |

## 13 页面规格

### 13.0 主站知识点只读页面

- 导航：只在有效登录态下显示“知识点”；点击进入 `/knowledge`。未登录直接访问路由，使用现有登录流程，登录后返回原目标。
- `/knowledge` 布局：桌面端上方为局部图谱，下方为知识点列表，右侧为当前知识点摘要；列表和图谱为主内容，摘要栏保持可见。移动端按“摘要、图谱、列表”顺序纵向排列，并允许图谱区折叠。
- 列表：关键词、分类、层级、重置、分页；点击整行选择知识点。当前项在列表中时显示唯一选中态；改变筛选后当前项可以暂时不在结果中，但上方图谱和右侧摘要保持不变。列表不显示状态筛选、新建、编辑、删除、审核计数或草稿标记。空结果说明筛选无结果，不当作报错，也不清除当前知识点。
- 局部图谱：初始不请求数据，显示选择引导；选择知识点后以该点为 root_code 查询上下游。区域只提供 depth、适应画布和“打开完整图谱”，不得出现关键词、分类、层级或状态筛选。required/recommended 使用不同线型；点击图中节点进入 `/knowledge/:code`。局部图谱不要求关系表格等价视图，完整图谱页必须提供。
- 摘要：未选择时显示占位说明；选中后展示名称、code、分类、层级、description、前置数和后继数，并提供醒目的“查看完整详情”。摘要不得显示内部版本、状态、创建人、审核信息或写操作。
- `/knowledge/graph`：提供完整图谱、节点搜索或根节点定位、category、level、depth、重置、图形和关系表格视图；无 root_code 时 depth 不生效。筛选写入本页 URL query，刷新和后退可恢复。
- 详情：展示名称、description、分类、层级、前置与后继、可见普通题链接；不显示创建人、版本、待审变更和审核人。非 active 知识点显示统一的 404 页面。
- 图谱通用规则：显示 required/recommended 线型和节点详情侧栏；完整图谱截断时提示缩小范围。依赖维护和审核不在主站图谱中操作。
- 管理跳转：Super Admin 可见“管理知识点”并跳转 `/admin/knowledge`；Admin+ALL/OWN 可见“前往题目管理”并跳转现有 `/admin/problems`；Regular User 和 Admin+NONE 没有知识模块管理跳转。跳转目标后仍由管理员端检查权限。
- 移动端：筛选区和图谱侧栏可折叠；题目链接沿用现有 OJ 普通题详情路由，不新增题目访问捷径。

以下 13.1 至 13.5 全部是管理员端页面规格，不适用于主站只读页。

### 13.1 管理员端知识点列表页

- 筛选区：关键词、分类、层级、状态；支持重置。

- 列表列：code、名称、分类、层级、状态、关联题目数、前置数、后继数、更新时间、操作。

- 只有 Super Admin 显示新建、编辑和状态变更按钮；未使用 draft 的详情可显示二次确认删除入口，必须填写原因；其他有权用户只读。

- 点击名称进入详情；点击图谱按钮携带当前知识点作为根节点。

- 分页默认 20；筛选条件写入 URL query，浏览器后退可恢复。

### 13.2 管理员端知识点详情页

- 基础信息区展示全部字段、创建人、时间、版本和状态。

- 前置依赖和后继依赖分别展示关系类型、权重和允许操作；待审变更单独以申请状态展示，不把申请伪装成正式边。

- 关联题目展示题号、标题、角色、权重和审核状态，点击打开题目标注页。

- 数据发生版本冲突时显示刷新提示，不自动覆盖本地输入。

### 13.3 管理员端知识图谱页

- 支持按分类、层级、根节点和深度筛选；有根时同时展示上游前置和下游后继，根节点显示为距离 0。

- 节点至少显示名称和层级；边区分 required 和 recommended。正式图不混入 pending 申请，待审内容从审核队列和详情查看。

- 点击节点在侧栏展示 description、前置、后继和关联题目摘要。

- 超过 500 节点时不全量绘制，页面显示截断提示并要求缩小范围。

- 图形组件不得成为唯一操作入口；依赖新增和审核必须有可访问的表单路径。

### 13.4 管理员端题目标注页

- 顶部显示题号、标题、公开状态、难度、现有标签和创建人，避免标错对象。

- 映射行包含知识点搜索、角色、权重和删除；主知识点只能选择一个。

- 提交前显示全部校验问题；接口失败时保留输入，不清空表单。

- 当前 approved 集合在页面上只读，不允许逐行直接修改；有题目标注权限的 Admin 可以基于 approved_version 另行提交新的 pending 替换批次。按钮依据接口返回 capabilities 展示，审核仍仅 Super Admin。

### 13.5 管理员端审核页

- 仅 Super Admin 可访问审核页和调用审核接口；普通 Admin 不显示入口，直接访问返回 403。

- 审核对象分为 dependency_change 和 problem_mapping，默认显示 pending。

- 队列只展示摘要，进入详情后再加载完整对象。题目标注详情展示题目摘要、版本和整组映射；依赖变更详情展示 operation、正式边当前值和拟变更值。

- 驳回原因必填；通过前二次确认，但不得使用含糊的通用确认文案。当前登录用户是提交人时，详情仍可查看，但不显示通过和驳回按钮，并说明“提交人不能审核自己的申请”。

- 审核冲突返回后刷新详情并提示已由其他人处理。

## 14 页面状态和错误处理

| 状态 | 页面行为 | 禁止行为 |
| --- | --- | --- |
| 加载中 | 保留页面骨架或表头，禁用重复提交 | 不得展示上一对象数据冒充新结果 |
| 探索页未选择 | 列表正常显示；局部图谱和摘要分别显示选择引导，不发起图谱请求 | 不得自动选择第一项或用固定示例冒充当前知识点 |
| 空数据 | 说明当前筛选无结果并提供重置筛选 | 不得当作系统错误 |
| 快速切换知识点 | 只允许最后一次选择对应的图谱响应更新页面 | 不得让较早响应覆盖当前知识点 |
| 401 | 提示登录失效并进入现有登录流程 | 不得无限重试 |
| 403 | 展示无功能权限 | 不得仅隐藏按钮而继续调用写接口 |
| 404 | 展示对象不存在或不在权限范围 | 不得泄露真实存在性 |
| 409 | 显示冲突原因并要求刷新 | 不得覆盖服务器最新数据 |
| 422 | 定位到具体字段或依赖关系 | 不得只显示保存失败 |
| 500 | 显示 request_id 供排障，可手动重试 | 不得显示堆栈或原始异常 |
| 未保存离开 | 二次确认保留或放弃 | 不得静默丢失输入 |

## 15 验收场景

| 编号 | 场景 | Given | When | Then |
| --- | --- | --- | --- | --- |
| AC-01 | 创建合法知识点 | 存在 Super Admin | 提交唯一 code 和合法字段 | 返回 201，status=draft，version=1 |
| AC-02 | 拒绝重复 code | bfs_basic 已存在 | 再次创建同 code | 返回 409，数据库只有一条 |
| AC-03 | 拒绝并发覆盖 | 两个客户端读取 version=3 | 先后保存不同修改 | 第一个成功，第二个返回版本冲突 |
| AC-04 | 受控废弃知识点 | 知识点仍有当前 approved 映射或依赖 | 执行物理删除或改为 deprecated | 物理删除被拒绝；废弃返回 409；先替换映射并删除依赖后才可废弃，历史审计保留 |
| AC-05 | 拒绝自环 | 知识点 A active | 提交 A→A | 返回 422，不写入 |
| AC-06 | 拒绝多节点环 | 已有 A→B、B→C | 提交 C→A | 返回 KNOWLEDGE_DEPENDENCY_CYCLE |
| AC-07 | 原子提交映射 | 题目可管理 | 20 条中 1 条权重非法 | 全部不保存并定位非法项 |
| AC-08 | 主知识点唯一 | 准备两个 primary | 提交映射集合 | 返回 422，提示必须且只能一个 |
| AC-09 | 隔离未审核数据 | 映射批次 status=pending | 调用普通题目标注查询接口 | 当前生效结果仍只包含旧 approved 集合 |
| AC-10 | 对象权限 | OWN 用户访问他人题目 | 读取或提交标注 | 统一返回 404 |
| AC-11 | 审核并发 | 两人打开同一 pending 对象 | 同时提交审核 | 只有一次成功，另一次返回 409 |
| AC-12 | 旧功能回归 | 部署新迁移 | 运行题目 提交 比赛 判题回归 | 现有行为与接口无不兼容变化 |
| AC-13 | 历史题兼容 | 已发布普通题没有知识映射 | 部署并读取或提交该题 | 旧功能正常；知识接口返回 unannotated 和 approved_version=0 |
| AC-14 | 映射替换隔离 | 题目当前 approved_version=3 | 提交 base_version=3 的新批次但尚未审核 | 普通查询仍返回 approved_version=3 的集合；同题第二个 pending 提交返回 409 |
| AC-15 | 拒绝过期批次 | 题目当前 approved_version=4 | 审核 base_version=3 的 pending 批次 | 返回 409，v4 集合完整保留 |
| AC-16 | 依赖权重下界 | 两个 active 知识点 | 提交 weight=0 的依赖 | 返回 422，不写入依赖或审计事件 |
| AC-17 | 拒绝普通管理员维护知识体系 | Admin+ProblemPermission.ALL 已登录 | 提交依赖或访问审核接口 | 返回 403，不创建依赖、不改变审核状态 |
| AC-18 | 未登录不可浏览 | 用户无有效 Session | 访问 `/knowledge` 或任一主站知识 API | 页面进入现有登录流程；接口为 401，data 无知识点内容 |
| AC-19 | 共同只读入口与分角色跳转 | Regular User、Super Admin、Admin+ALL/OWN、Admin+NONE 分别已登录 | 点击主站“知识点”并查看列表 | 都进入同一只读页；Super Admin 跳 `/admin/knowledge`，ALL/OWN 跳 `/admin/problems`，其余无管理跳转；主站无保存按钮 |
| AC-20 | 未生效数据隔离 | active、draft、deprecated 点、正式依赖及 pending/rejected 变更申请并存 | 已登录学生查询主站列表、详情、图谱 | 仅 active 点与两端 active 的正式依赖返回；非 active 详情 404；无申请、审核和审计字段 |
| AC-21 | 关联题目可见性 | 同点有 visible 普通题、hidden 普通题、比赛题以及待审映射 | 已登录学生查看主站详情 | 仅 visible=true、contest 为空且映射 approved 的普通题编号与标题返回；其他题及其计数不泄露 |
| AC-22 | 主站无写入与管理端授权 | Regular User 和 Admin+NONE 已登录 | 伪造主站写请求，再直接访问管理员端写 API | 主站无写接口；管理端服务端拒绝越权，数据不变 |
| AC-23 | 导航和状态恢复 | 已登录用户正在使用列表或完整图谱筛选 | 刷新、后退、退出登录 | 各页自身筛选可从 URL 恢复；退出后知识点入口消失、当前页面进入登录流程，旧数据不残留 |
| AC-24 | 已批准依赖受控维护 | approved 边 version=3 | Super Admin 提交 update/delete 申请 | 返回 pending 申请，主站和管理员正式图继续显示旧边；批准后原子更新或删除，驳回后旧边不变 |
| AC-25 | 废弃前待审引用隔离 | active 点仍被 pending 依赖变更申请或待审映射批次引用 | Super Admin 尝试 deprecated | 返回 409，状态不变；处理待审对象和当前正式引用后可废弃 |
| AC-26 | 已批准标注替换权限 | Admin+OWN 对本人普通题有 approved v3 | 从管理员端基于 v3 提交新批次 | approved 行仍只读但可提交 pending v4；审核前主站继续返回 v3 |
| AC-27 | 图谱筛选与截断稳定性 | active 根节点、双向关系、分类筛选和超过 500 个节点的图并存 | 查询主站或管理员端图谱 | 非 active 根 404；根距为 0 且始终保留；上下游均按 depth 遍历后过滤；按 distance、code 截断至多 500 节点，无悬空边 |
| AC-28 | 删除未使用草稿 | Super Admin 持有未被引用 draft 的当前 version | 填写原因并二次确认管理端删除命令 | 返回 204；知识点消失，knowledge_point/deleted 事件保存 code、版本、原因和受限前快照，不保存描述与 metadata |
| AC-29 | 拒绝越界删除 | active 或 deprecated 点、被历史批次引用的 draft、过期 version 或缺少原因 | 分别尝试管理端删除命令 | 状态/引用/版本冲突 409、原因缺失 400；原点与审计均不改变 |
| AC-30 | 依赖申请审核并发 | 同一 approved 边已有 pending update 申请 | 再提交 update/delete 或两人同时审核 | 第二个申请或后到审核返回 409；正式边最多改变一次 |
| AC-31 | 批次与批准版本分离 | batch v1 已批准、v2 被驳回 | 提交并批准 v3 | v3 的 batch_version=3、approved_version=2，客户端 base_version 始终使用 1 再变为 2 |
| AC-32 | 管理列表和详情完整 | 管理账号查询列表后进入详情 | 查看计数、依赖、题目和 capabilities | 列表计数与详情口径一致；无 N+1；题目摘要按对象权限过滤 |
| AC-33 | 审核摘要与详情分离 | 队列同时含 dependency_change 和 problem_mapping | 搜索筛选并打开详情 | 队列不含完整 payload；详情按 object_type 返回完整且可判别结构 |
| AC-34 | 新旧响应兼容 | 旧接口与知识模块新接口共存 | 分别由旧页面和知识页面调用 | 全局 ajax 与旧接口响应不变；knowledgeRequest 正确处理包络、4xx、request_id 和 204 |
| AC-35 | 禁止提交人自审 | Super Admin A 提交依赖变更或题目标注批次，Super Admin B 可审核 | A 分别尝试 approve 和 reject，随后 B 审核 | A 两次均收到 403 KNOWLEDGE_SELF_REVIEW_FORBIDDEN，详情 capabilities 无 approve/reject，业务数据与审计不变；B 可按规则完成审核并留下双方身份 |
| AC-36 | 探索页按选择加载局部图谱 | 已登录用户首次进入 `/knowledge`，列表包含 `bfs_basic` | 首次加载、点击 `bfs_basic`、随后改变列表 category 或分页 | 首次不请求图谱且两处显示选择引导；点击后只以 `root_code=bfs_basic` 和当前 depth 请求图谱并同步摘要；改变列表条件只刷新列表，当前图谱和摘要保持；图谱区无关键词、分类或层级筛选 |

## 16 非功能和安全要求

| 类别 | 要求 |
| --- | --- |
| 性能 | 列表和审核接口 P95 小于 500ms；根节点深度不超过 3 的图查询 P95 小于 1s，均以 10 万映射规模压测。 |
| 分页 | 列表默认 20，上限 100；审核队列必须稳定排序，禁止一次返回全量数据。 |
| 事务 | 防环检查、映射集合替换和审核状态变更必须在事务中完成。 |
| 安全 | 主站读请求也必须校验 Session；写请求校验 Session 和 CSRF；服务端执行权限与数据可见性判断，前端隐藏按钮不构成安全控制。 |
| 日志 | 错误日志包含 request_id、用户 ID、动作和对象标识；不得记录 Session、完整学生代码、隐藏测试点或标准答案。 |
| 可访问性 | 所有图形信息提供文本或表格等价视图；表单字段有可读标签，键盘可完成核心操作。 |
| 兼容性 | 不改变现有旧系统 API 的字段语义；知识模块草案统一使用 X-API-Version: 0.9.9，四方批准后整体冻结为 1.0.0。 |

## 17 数据迁移 发布和回滚

### 17.1 发布步骤

1. 上游数据模型变更提案批准并合入；补录可验证的前后端 Git commit；将交付包内两份 AGENTS.md 安装到对应代码库根目录。

1. 上线仅创建 knowledge_point、knowledge_dependency、knowledge_dependency_change_request、problem_knowledge、knowledge_mapping_batch、knowledge_review_event 及必要索引和约束。

1. 执行迁移前备份数据库并记录当前 migration 状态。

1. 不得为历史题批量生成空映射或伪造主知识点；历史普通题在无 approved 集合时由查询服务派生为 unannotated。

1. 导入经产品和教师确认的 BFS、DFS draft 种子数据；先 dry-run，再正式导入。

1. 部署后先只向审核人员开放管理员端功能开关，完成数据和权限验收。

1. 通过旧功能回归后再向题目管理人员开放标注入口；主站专用 API 完成匿名 401、待审隔离、隐藏题与比赛题过滤验收后，才向已登录用户显示知识点入口。

### 17.2 回滚原则

- 前端可分别通过功能开关隐藏主站只读入口和管理员端管理入口，不影响旧题目与旧管理端。

- 后端路由可停用，但已写入的新表数据应保留，禁止在紧急回滚中直接删表。

- 数据库结构回滚仅在确认无业务数据或已完成可验证备份恢复演练后执行。

- 任何回滚不得恢复到会让普通查询返回 pending 或 rejected 数据的代码版本。

## 18 开发 Agent 约束

开发 Agent 只能实现本 PRD 和机器契约已经确定的内容，不是产品决策者或业务审批者。每次任务只实现一张任务卡，不允许为假设中的未来功能增加字段、接口、抽象层、缓存或扩展点。

| 约束 | 要求 |
| --- | --- |
| 变更边界 | 仅修改任务卡列出的目录和必要接入文件；发现需要扩大范围时停止并报告。 |
| 依赖 | 禁止新增或升级 Python、npm、数据库和系统依赖，除非任务卡明确批准。 |
| 架构 | 禁止重写旧框架、替换路由、改造全局响应或引入新图数据库；响应兼容只在知识模块专用基类和适配器内完成。 |
| 契约 | 不得自行改字段名、枚举、状态机、错误码或默认分页；冲突时停止。 |
| 数据 | 不得批量修改现有题目标签、难度和历史提交；不得使用生产数据做破坏性测试。 |
| 权限 | 不得以隐藏前端按钮代替后端授权；不得放宽 404 隐匿规则。 |
| 实现方式 | 优先复用现有 APIView、JSONResponse、权限装饰器以及主站、管理端各自的请求和 UI 模式；不得向学生直接透传管理员端响应。 |
| 验证 | 每个业务规则必须有正例和至少一个反例；先运行定向测试，再运行相关回归。 |
| 提交结果 | 输出变更文件、迁移影响、测试命令和结果、未解决问题；禁止声称未执行的测试已通过。 |

### 18.1 开发 Agent 必须停止并询问的情况

- `data-model-change-proposal-v0.9.8.md` 尚未合入上游冻结数据模型，或前后端基线 commit 尚未补录。

- PRD、OpenAPI、冻结数据模型、模块级 AGENTS.md 或现有代码语义相互冲突。

- 必须修改禁止目录、公共响应结构、现有权限语义或依赖版本。

- 迁移会重写、删除或无法回滚现有业务数据。

- 验收标准无法通过确定性测试，或需要由模型判断测试是否成功。

- 发现安全问题、权限绕过、敏感数据泄漏或隐藏测试点暴露风险。

- PRD、OpenAPI、数据契约、任务卡或快照 Schema 对路径、字段、匿名 401、依赖维护原因、废弃前置条件及题目过滤存在冲突；不得按个人理解自行补齐契约。

## 19 开发拆分和完成定义

| 任务 | 交付内容 | 前置 | 完成定义 |
| --- | --- | --- | --- |
| KP-DEV-001 | 核心模型 依赖变更申请 映射批次 审计事件 迁移 数据约束 | 上游模型变更已合入 数据契约批准 AGENTS 已安装 commit 已记录 | 迁移正反向检查 模型约束和快照 Schema 测试通过 |
| KP-DEV-002 | 知识点领域服务和管理 API | 001 | CRUD 权限、草稿删除审计、并发和状态机测试通过 |
| KP-DEV-003 | 依赖图服务和防环 | 001 | 自环 重复边 多节点环 事务测试通过 |
| KP-DEV-004 | 题目映射和审核 API | 001 002 | 原子性 主知识点 权限 审核隔离测试通过 |
| KP-DEV-005 | 管理端知识点页面 | 002 003 | 五类页面状态和权限显示通过 |
| KP-DEV-006 | 题目标注和审核页面 | 004 | 表单校验 冲突处理 输入保留通过 |
| KP-DEV-007 | 主站专用只读 API | 002 003 004 且主站契约批准 | active 点、正式依赖、visible 普通题隔离、匿名 401、非 active 404 测试通过 |
| KP-DEV-008 | 主站探索 详情 完整图谱与导航 | 007 | 三页只读状态、选择后加载局部图谱、筛选职责和恢复、登录态切换及管理员端跳转通过 |
| KP-DEV-009 | 契约和回归验证 | 001 至 008 | OpenAPI 解析 AC-01 至 AC-36 旧功能回归通过 |

模块完成定义：全部高优先级需求实现；机器契约、数据库约束、接口行为、前端页面和验收用例一致；不存在 P0/P1 缺陷；迁移和回滚步骤完成演练；产品、后端、前端和测试负责人签字确认。

本交付包的 PRD、OpenAPI、数据契约和任务卡在草案层面已同步，但仍须产品、后端、前端、测试确认并冻结为 1.0.0，才可派发开发 Agent。冻结前不得把“文件版本一致”误认为业务方案已经批准。

## 20 已确认决策和待评审项

下列项目均为产品已确认结论。评审可以提出实现风险或正式变更申请，但开发 Agent 不得把这些结论重新解释为可选默认值。

本轮已确认的产品决策：未登录用户不能浏览知识点；主站只提供只读页面；`/knowledge` 使用列表驱动的组合探索布局并在点击列表项后加载局部图谱；知识点 CRUD、依赖维护、题目标注和审核留在管理员端；所有依赖新增、修改和删除都经过变更申请审核；题目标注使用 batch_version 与 approved_version 双版本；有根图双向遍历后过滤且始终保留根；管理列表、详情、审核详情采用本版字段边界；知识接口使用模块专用响应适配层；前后端分别使用模块级 AGENTS.md；提交人不得审核自己的申请。这些项目不再由开发 Agent 选择。

产品已确认 D-01 至 D-17 的业务结论。后端、前端和测试仍需确认可实现性、契约一致性和验收覆盖；上游数据模型变更、实际源码 commit 与四方签字仍是冻结条件，不能因为产品确认而跳过。

| 编号 | 决策 | 产品确认结论 | 变更影响 |
| --- | --- | --- | --- |
| D-01 | 一期是否建立独立教师角色 | 否，复用现有 AdminType 和 ProblemPermission | 需要新增权限模型和迁移 |
| D-02 | 每题主知识点数量 | 恰好一个 | 影响服务校验 导入和页面展示 |
| D-03 | 权重是否必须求和为 1 | 否，由消费方确定性归一化 | 影响编辑器和历史数据兼容 |
| D-04 | 是否强制审核人与提交人不同 | 是；依赖变更和题目标注的提交人均不得 approve 或 reject 自己的申请，后端返回 403，审计记录提交人和实际审核人 | 需要对象级审核授权、详情 capabilities、错误码和正反向验收用例 |
| D-05 | 是否支持比赛题 | 一期不支持 | 涉及比赛权限和题目可见性 |
| D-06 | deprecated 是否允许恢复 | 不允许 | 影响历史语义和当前生效数据查询 |
| D-07 | 依赖图最大节点数 | 500 | 影响前端性能和接口截断规则 |
| D-08 | 首批种子知识点 | 采用附录清单，教师确认后 active | 影响后续所有映射 |
| D-09 | 历史题是否强制补标 | 否，默认 unannotated；按运营计划逐步补标 | 若强制会阻断迁移或需要批量人工审核 |
| D-10 | approved 依赖能否由 Super Admin 直接维护 | 已确认不可以；update/delete 均创建独立变更申请，旧边批准前继续生效 | 已由 KnowledgeDependencyChangeRequest、审核详情和 API 固化 |
| D-11 | 当前引用中的知识点能否 deprecated | 不允许；先处理 pending 和当前 approved 引用，历史批次/审计保留 | 若允许，主站 active-only 查询与当前映射集合的主知识点可能不一致 |
| D-12 | 知识点物理删除范围 | 仅从未被引用的 draft；需原因、版本和受限快照审计；active/deprecated 禁止物理删除 | 若扩大删除范围，历史引用、审计与主站语义必须重设计 |
| D-13 | 映射版本语义 | 已确认 batch_version 每次提交递增，approved_version 仅批准递增 | 已由批次字段、base_version 和 AC-31 固化 |
| D-14 | 有根图遍历和过滤 | 已确认上下游双向遍历；先遍历后过滤；根始终保留；按 distance、code 截断 | 已由 KD-FR-001、SP-FR-003 和 AC-27 固化 |
| D-15 | 新旧接口响应兼容 | 已确认增加 KnowledgeAPIView 与 knowledgeRequest，不改全局响应层 | 已由第 6、16、18 节和 AC-34 固化 |
| D-16 | 上游数据模型冲突 | 已确认以本需求为目标，通过正式变更提案修改上游；合入前禁止开发 | 需后端架构负责人批准并更新上游文件 |
| D-17 | 主站探索页筛选和加载职责 | `/knowledge` 的列表负责 keyword/category/level/page/page_size；首次不加载局部图谱，点击列表项后以 root_code+depth 加载；列表筛选变化不清空当前图谱；完整图谱筛选留在 `/knowledge/graph` | 需要同步页面规格、前端任务卡、接口调用约束和 AC-36，不改变图谱接口参数集合 |

## 附录 A BFS 和 DFS 种子知识点建议

以下仅作为首批产品种子清单。正式导入前需要算法课程教师确认名称、边界、层级和依赖。机器 code 一旦发布不得修改。

| code | 名称 | 分类 | 层级 | 建议直接前置 |
| --- | --- | --- | --- | --- |
| graph_basic | 图的基本概念 | graph | 1 | 无 |
| adjacency_representation | 图的邻接表示 | graph | 1 | graph_basic |
| queue_basic | 队列基础 | data_structure | 1 | 无 |
| recursion_basic | 递归基础 | basic | 1 | 无 |
| bfs_basic | BFS 基础遍历 | graph | 2 | adjacency_representation queue_basic |
| grid_bfs | 网格图 BFS | graph | 2 | bfs_basic |
| bfs_shortest_path | 无权图 BFS 最短路 | graph | 3 | bfs_basic |
| multi_source_bfs | 多源 BFS | graph | 4 | bfs_shortest_path |
| dfs_basic | DFS 基础遍历 | graph | 2 | adjacency_representation recursion_basic |
| dfs_connected_components | DFS 连通块 | graph | 3 | dfs_basic |
| dfs_cycle_detection | DFS 环检测 | graph | 3 | dfs_basic |
| topological_sort | 拓扑排序 | graph | 4 | dfs_cycle_detection |

## 附录 B 知识模块错误码

| 错误码 | HTTP | 含义 |
| --- | --- | --- |
| KNOWLEDGE_AUTH_REQUIRED | 401 | 未登录或 Session 失效 |
| KNOWLEDGE_PERMISSION_DENIED | 403 | 无功能权限 |
| KNOWLEDGE_SELF_REVIEW_FORBIDDEN | 403 | 提交人不能审核自己的依赖变更或题目标注申请 |
| KNOWLEDGE_NOT_FOUND | 404 | 对象不存在或不在权限范围 |
| KNOWLEDGE_INPUT_INVALID | 400 | 字段 类型 枚举或分页参数非法 |
| KNOWLEDGE_CODE_CONFLICT | 409 | code 已存在 |
| KNOWLEDGE_NAME_CONFLICT | 409 | normalized_name 已存在 |
| KNOWLEDGE_VERSION_CONFLICT | 409 | 乐观锁版本冲突 |
| KNOWLEDGE_STATE_CONFLICT | 409 | 当前状态不允许操作 |
| KNOWLEDGE_SELF_DEPENDENCY | 422 | 依赖自身 |
| KNOWLEDGE_DEPENDENCY_EXISTS | 409 | 依赖边重复 |
| KNOWLEDGE_DEPENDENCY_CYCLE | 422 | 新增边形成有向环 |
| KNOWLEDGE_MAPPING_INVALID | 422 | 题目映射集合违反业务规则 |
| KNOWLEDGE_REVIEW_CONFLICT | 409 | 审核对象已被处理 |
| KNOWLEDGE_INTERNAL_ERROR | 500 | 未预期内部错误 |

## 附录 C 参考依据

- 原始需求文档：D:\Homework\da_chuang\first_time\需求文档.docx。

- 现有冻结数据契约：XMUOJ-AI 第一期后端契约交付中的 data-structure-contract-v1.md 和 data-model-v1.md。

- 本版数据模型变更提案：交付包中的 data-model-change-proposal-v0.9.8.md；尚未合入上游，不构成已批准模型。

- 现有接口规范：api-versioning-v1.md、api-error-codes-v1.md 和 contract-change-policy-v1.md。

- 现有代码基线：XMUOJ 的 Problem、User、管理端 router.js、SideMenu.vue 和 oj/urls.py。

- 基线采集结果：提供的源码与契约目录均无 `.git`，无法记录 commit。冻结前必须在实际前后端 Git 仓库补录 40 位 commit hash。
