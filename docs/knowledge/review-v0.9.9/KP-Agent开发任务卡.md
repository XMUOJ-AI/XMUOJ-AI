# XMUOJ 知识点体系模块 Agent 开发任务卡

- 版本：0.9.9
- 状态：阻断，待上游模型合入和四方冻结
- 规则：一次开发 Agent 运行只领取一张任务卡

## 通用执行契约

1. 本任务卡目前禁止发放。只有 `data-model-change-proposal-v0.9.8.md` 已合入上游模型、README 已补录前后端 40 位 Git commit、两份模块级 AGENTS.md 已安装到对应仓库根目录、四方确认并冻结为 1.0.0 后，才可领取任务。
2. 开始前读取代码库根目录 AGENTS.md、上游已批准数据模型、XMUOJ知识点体系模块PRD_v0.9.9.md、knowledge-data-contract-v1.md、knowledge-api-v1.yaml、knowledge-snapshot-schema-v1.json 和目标目录代码。Word PRD 只用于人工评审。
3. 不升级 Vue 2、Webpack 3、Element UI、Django、数据库或项目依赖。
4. 不修改判题、提交、比赛、登录、现有题目标签、全局 APIView、JSONResponse 或 ajax 的公共响应语义。知识模块只使用专用 KnowledgeAPIView 和 knowledgeRequest。
5. 不引入图数据库；知识依赖使用关系表与领域服务。
6. 不让模型参与知识点、依赖、映射或审核的业务判断。
7. 主站三个 GET 接口必须校验 Session 且只返回 active 知识点、正式依赖和 visible 普通题当前映射；所有写接口校验 Session、CSRF、功能权限和对象权限。
8. ALL、OWN、NONE 是 ProblemPermission 枚举值，不是独立角色；不得用 ProblemPermission.ALL 推导知识体系维护或审核权限。
9. 每条核心规则至少提供一个正例和一个反例测试。
10. 若契约冲突、必须扩大修改范围、需要新依赖或迁移会改写历史数据，立即停止并报告。
11. 最终报告必须列出变更文件、迁移影响、实际执行的测试及结果、剩余风险；不得把未运行测试写成通过。
12. 未登录用户不可浏览知识点；主站只读，CRUD、依赖维护、题目标注和审核都在管理员端。不得直接透传管理员端序列化器。
13. 依赖变更和题目标注的提交人均不得 approve 或 reject 自己的申请；详情 capabilities 只控制界面，后端必须比较当前用户和 submitted_by，自审返回 403 `KNOWLEDGE_SELF_REVIEW_FORBIDDEN` 且不写业务数据或审计。
14. 正式依赖只保存当前生效边；所有 create/update/delete 都创建独立变更申请。batch_version 与 approved_version 不得混用。
15. `/knowledge` 是列表驱动的组合探索页：首次不请求局部图谱；点击列表项后才以 root_code 和 depth 请求图谱。列表独占 keyword、category、level、page、page_size；局部图谱不得复制这些筛选，也不得因列表筛选变化而清空当前选择。

## KP-DEV-001 模型与迁移

**目标**：实现 KnowledgePoint、正式 KnowledgeDependency、KnowledgeDependencyChangeRequest、ProblemKnowledge、KnowledgeMappingBatch、KnowledgeReviewEvent 及数据库约束。

**允许修改**：新建后端 knowledge app；Django app 注册；对应 migration 和测试；必要的 `oj/urls.py` 接入暂不开放业务接口。

**禁止修改**：Problem、Submission、User 既有字段和主键；历史题目标签、难度和提交数据。

**必须验证**：正式依赖有向对唯一、同目标单 pending 申请、weight 大于 0、batch_version 与 approved_version 双版本、同题单 pending 批次、外键策略、审计事件只追加、快照 Schema、迁移前后状态。多节点防环不在模型 save 中隐式实现。

**完成条件**：空库迁移通过；从当前数据库迁移通过；模型约束测试通过；回滚影响有说明。

## KP-DEV-002 知识点服务与 API

**目标**：完成知识点列表、详情、创建、编辑、状态机，以及仅未使用 draft 的受控删除命令。

**允许修改**：knowledge app 的管理 service、serializer、view、url、test；`oj/urls.py` 的管理接口 include，不提前开放主站接口。

**禁止修改**：全局 JSONResponse 行为和现有权限装饰器语义。需要复用时可组合，不得放宽。

**必须验证**：code 和 normalized_name 冲突、level、状态跳转、version 乐观锁、401/403/404、分页与计数稳定性、详情 capabilities、摘要权限和固定查询数；有 pending 依赖变更申请/映射批次或当前正式依赖/映射时 deprecated 返回 409；管理端 POST 删除命令仅允许从未被正式依赖、依赖变更申请、映射行或映射批次引用的 draft，原子写受限审计再删点。active/deprecated 不得物理删除。

## KP-DEV-003 依赖图与防环

**目标**：完成正式图查询、依赖变更申请、审核和事务防环。

**权限**：Admin+ALL 和 Admin+OWN 只能查看依赖图；依赖提交、审核、变更和删除仅 Super Admin。

**算法要求**：批准 create/update 前用确定性 BFS/DFS 检查拟生效边后是否可从 dependent 到达 prerequisite；检查、正式边写入和审计在同一事务中。有根图同时沿 prerequisite 上游和 dependent 下游遍历，根距离 0，一条边距离 1。

**必须验证**：自环、重复边、两节点环、多节点环、菱形无环图、并发申请与审核；create/update/delete 均先创建申请，update/delete 批准前旧边保持；同目标单 pending；base_version；提交人 approve/reject 均为 403 且不写审计，其他 Super Admin 可审核；驳回不改正式图；非 active 根 404；先双向遍历后过滤且根保留；无根时 depth 被忽略；按 distance、code 截断至 500 且无悬空边。

**禁止行为**：使用非确定性模型判断是否构成依赖；在前端完成唯一防环校验；全表无上限返回图数据。

## KP-DEV-004 题目映射与审核

**目标**：实现普通题映射集合查询、原子提交、审核通过和驳回。

**权限**：Super Admin 可操作全部普通题；Admin+ALL 可操作全部普通题；Admin+OWN 仅操作本人创建的普通题；审核仅 Super Admin。

**必须验证**：恰好一个 primary、知识点去重、1 至 20 项、权重范围、active 限制、base_version 只引用 approved_version、batch_version 每次提交递增、approved_version 只在批准时递增、同题单 pending、旧集合持续可读、批次原子批准、审核并发、提交人不得 approve/reject 自己的批次、比赛题拒绝。覆盖“v1 批准、v2 驳回、v3 批准后 approved_version=2”。

## KP-DEV-005 管理端知识点页面

**目标**：实现列表、详情和图谱页面。

**允许修改**：`src/pages/admin/views/knowledge/`、views 导出、admin router、SideMenu、admin api、对应语言文案和测试。

**允许的接入**：新增知识模块专用 `knowledgeRequest` 与 API 文件；现有 admin api 只做导出接入。

**禁止修改**：package.json、全局路由模式、现有页面组件结构、公共 ajax 返回语义。

**必须验证**：列表三个计数、详情三类摘要与 capabilities、固定查询口径、加载、空、失败、无权限、冲突、双向图、截断图、路由顺序、筛选恢复；未使用 draft 的删除入口仅 Super Admin 可见，有二次确认、原因字段和失败时输入保留；knowledgeRequest 正确处理包络、4xx、request_id 和 204。

## KP-DEV-006 题目标注和审核页面

**目标**：实现映射编辑器、审核摘要队列和审核详情。

**权限**：审核队列和审核动作仅 Super Admin；普通 Admin 只按 ProblemPermission 范围使用题目标注页。

**必须验证**：主知识点单选、权重范围、知识点去重、双版本显示、提交失败保留输入、object_type/submitter/status/更新时间/关键词筛选、队列无完整 payload、详情判别结构、依赖 before/proposed、驳回原因、审核并发刷新、capabilities 控制按钮；提交人查看自己的申请时无 approve/reject，并显示不能自审说明。

**页面边界**：当前 approved 行只读，但有题目标注权限的 Admin 可基于 approved_version 提交新的 pending 替换批次；不得误做成“普通 Admin 无法修改标注”。

## KP-DEV-007 主站专用只读 API

**目标**：实现 GET `/api/knowledge-points`、`/api/knowledge-points/{knowledge_code}`、`/api/knowledge-graph`，供已登录用户只读浏览。

**允许修改**：knowledge app 的 public service、独立投影 serializer、view、url、test；`oj/urls.py` 增加只读接口 include。不得修改现有 OJ 题目列表/详情语义或管理员端响应字段。

**必须验证**：匿名或 Session 失效 401；所有已登录身份可读；仅 active 点、正式边和 visible 普通题当前映射；非 active 详情或 root_code 为 404；有根图先双向遍历后过滤且根保留；无根 depth 被忽略；`/knowledge` 的局部图请求只传 root_code 和 depth，完整图谱仍支持 category/level；关联题不泄露隐藏题、比赛题或待审计数；主站无写方法；列表和详情稳定排序；按 distance、code 截断至 500 且无悬空边。

**禁止行为**：复用管理员端详情 serializer、放开匿名访问、在主站返回 normalized_name、内部 id、status、version、metadata、审核快照或审计记录。

## KP-DEV-008 主站只读页面与导航

**目标**：实现主站 `/knowledge` 组合探索页、`/knowledge/graph` 完整图谱页、`/knowledge/:code` 详情页及登录后“知识点”入口。

**允许修改**：现有 OJ 前端 router、导航、知识模块专用 knowledgeRequest 与 API、独立 knowledge 页面目录、对应文案和定向测试；不改全局 ajax、路由方案或旧题目页面。

**必须验证**：静态 graph 路由先于动态详情；`/knowledge` 首次只加载列表并显示图谱/摘要选择引导，不自动选第一项；点击列表行才以 root_code+depth 加载局部图谱和摘要且不改路由；列表 keyword/category/level/page/page_size 写入 URL 并可恢复；列表筛选或分页变化不清空当前知识点；局部图谱区没有关键词、分类、层级筛选；“查看完整详情”和“打开完整图谱”分别跳转正确；`/knowledge/graph` 的筛选、定位和关系表格等价视图可用；登录/登出/Session 失效状态；空、加载、401、404、500 与截断图；Super Admin 跳 `/admin/knowledge`，Admin+ALL/OWN 跳 `/admin/problems`，NONE 与 Regular User 无管理跳转；主站没有写表单或按钮。测试数据和路由示例统一使用附录种子 code `bfs_basic`，不得臆造 `bfs`。

## KP-DEV-009 契约与回归

**目标**：验证机器契约和旧系统兼容性。

**必须执行**：OpenAPI 解析和全量 `$ref` 检查、快照 Schema 正反例、接口 Schema 正反例、主站与管理端权限矩阵、AC-01 至 AC-36、迁移检查、知识模块全量测试、题目管理回归、普通题读取、提交与判题相关回归。

**发布阻断**：上游模型提案未合入、commit 未记录、AGENTS 未安装；主站允许匿名浏览或泄露未生效/不可见数据；当前引用知识点可被废弃；越界物理删除；依赖绕过变更申请；双版本混用；图谱过滤或截断不符合契约；修改全局响应导致旧接口不兼容；迁移需要未经评审地改写历史业务数据。
