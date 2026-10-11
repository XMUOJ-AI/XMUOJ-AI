# XMUOJ 知识点体系模块评审包

当前版本为 0.9.9，仅用于产品、后端、前端和测试评审。知识点 CRUD、依赖维护、题目标注和审核位于管理员端；主站只向已登录用户提供探索、详情和完整图谱只读页面。产品已确认 D-01 至 D-17；`/knowledge` 采用列表驱动的组合探索布局，点击列表项后才加载局部图谱。

本包不是可派发开发 Agent 的冻结包。上游数据模型变更尚未批准，提供的源码和契约目录也没有 `.git`，无法记录可验证的 commit。完成下列冻结条件前，任何 Agent 都不得开始实现。

## 当前文件

- `XMUOJ知识点体系模块PRD_v0.9.9.md`：业务规则唯一可编辑源文件。
- `XMUOJ知识点体系模块PRD_v0.9.9.docx`：与 Markdown 同版本的人工评审文件。
- `knowledge-api-v1.yaml`：OpenAPI 3.0.3 机器契约，版本 0.9.9。
- `knowledge-data-contract-v1.md`：目标数据结构、事务和查询规则。
- `knowledge-snapshot-schema-v1.json`：审核快照 JSON Schema。
- `frontend-prototype-spec-v0.9.9.md`：三条主站路由的页面职责、触发时机、筛选归属和竞态处理。
- `data-model-change-proposal-v0.9.8.md`：提交给上游数据模型负责人的正式变更提案。
- `backend-difference-archive-v0.9.8.md`：现有后端源码、冻结模型与目标设计之间的集中差异归档。
- `KP-Agent开发任务卡.md`：冻结后逐张发放的任务边界。
- `agent-baseline/backend/AGENTS.md`：待复制到实际后端 Git 仓库根目录的模块约束模板。
- `agent-baseline/frontend/AGENTS.md`：待复制到实际前端 Git 仓库根目录的模块约束模板。
- `archive/`：旧版本，仅供追溯，不得加入 Agent 开发包。

## 本版已确认规则

1. 未登录用户不能浏览知识点；主站共同入口只读，CRUD 和审核留在管理员端。
2. 正式 KnowledgeDependency 只保存当前生效边。create、update、delete 都提交独立变更申请；update/delete 审核前旧边继续生效。
3. 题目标注的 batch_version 每次提交递增，approved_version 只在批准时递增，base_version 只引用 approved_version。
4. 有根图同时遍历上游和下游，根距离为 0；先遍历后过滤，根始终保留；超过 500 节点按 distance、code 截断，边不得悬空。
5. 管理列表返回三个计数；管理详情返回基础信息、capabilities、依赖和题目摘要；审核队列只返回摘要，完整内容由审核详情接口返回。
6. 知识模块使用专用 KnowledgeAPIView 和 knowledgeRequest，不修改旧接口的全局响应处理。
7. 前后端分别安装模块级 AGENTS.md 后才能发放任务。
8. 不新增教师角色；每题一个主知识点；权重不要求提交时求和为 1；一期不支持比赛题；deprecated 不恢复；图谱上限 500；首批种子经教师确认后激活；历史题不强制补标；有引用时不得废弃；仅未引用 draft 可审计后物理删除。
9. 提交人不得 approve 或 reject 自己的依赖变更或题目标注申请；自审返回 403，详情不给出审核 capabilities，业务数据和审计不改变。
10. `/knowledge` 首次只加载列表；点击列表项后才以 root_code 和 depth 加载局部图谱。keyword、category、level、page、page_size 只属于列表，完整图谱筛选保留在 `/knowledge/graph`。

## 冻结门槛

1. 后端负责人逐项关闭 `backend-difference-archive-v0.9.8.md` 的阻断项，批准 `data-model-change-proposal-v0.9.8.md`，并将全部修改合入上游 `data-model-v1.md` 和迁移规范。
2. 在实际前端和后端 Git 仓库中记录 40 位 commit，并替换下表的“不可用”。
3. 将两份 AGENTS.md 复制到对应仓库根目录，确认不会与仓库已有指令冲突。
4. OpenAPI、快照 Schema、PRD、数据契约和任务卡校验通过，字段与状态机一致。
5. 产品、后端、前端和测试负责人签字；整体版本冻结为 1.0.0。
6. 只将当前冻结文件和 AGENTS.md 打入 Agent 开发包；排除 archive、旧 Word、旧 ZIP、渲染图和工作脚本。

| 基线 | 路径 | commit | 采集时间 | 处理 |
|---|---|---|---|---|
| 现有系统源码 | `D:\Homework\da_chuang\first_time` | 不可用，目录无 `.git` | 2026-09-16 | 冻结前改用实际 Git 仓库并补录 |
| 上游后端契约 | `D:\Homework\da_chuang\2026.9.6\XMUOJ-AI-第一期后端契约交付-2026-08-11` | 不可用，目录无 `.git` | 2026-09-16 | 合入模型变更后补录实际仓库 commit |

## 评审顺序

产品已确认 PRD 第 20 节全部业务决策；后端先阅读 `backend-difference-archive-v0.9.8.md`，再评审数据模型提案、事务、防环、禁止自审的对象级授权和响应基类；前端重点评审 `frontend-prototype-spec-v0.9.9.md`、路由、筛选职责、请求竞态、knowledgeRequest、capabilities 和页面字段；测试将 AC-01 至 AC-36 转为自动化用例。任何一方发现冲突，应修改全部受影响契约并重新评审，不能只改单个文件。
