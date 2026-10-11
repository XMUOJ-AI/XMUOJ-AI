> 2026-10-07 版本提示：本文保留第一期旧基线。知识点目标需求以 [新交付包 v0.9.9](knowledge/review-v0.9.9/README.md) 为准，但仍待模型批准和契约修正；本文相关内容不是当前已冻结实施规范。详见 [契约评审报告](reviews/contract-review-2026-10-07.md)。

# XMUOJ-AI 第一期数据结构契约

- 状态：已冻结
- 版本：1.0.0
- 更新日期：2026-08-10
- 交付任务：确定第一期数据结构

## 1. 文件定位

本文件是“确定数据结构”任务的唯一权威入口，汇总数据库结构、数据边界、权限原则和机器 Schema 的交付范围。为保持 JSON Schema 可被标准工具直接解析，具体机器契约仍作为本文件的附件独立保存，不把 JSON 内容嵌入 Markdown。

发生冲突时按下列优先级解释：

1. 数据库字段、枚举、约束、索引、外键删除策略和权限边界以 [data-model-v1.md](./data-model-v1.md) 为准。
2. 交换数据的字段类型、必填项、格式和条件约束以 `docs/schemas/` 下对应 JSON Schema 为准。
3. 示例只用于说明，不覆盖前两项规范。

## 2. 数据域和结构范围

第一期结构分为以下数据域：

| 数据域 | 核心对象 | 详细定义 |
|---|---|---|
| 现有 OJ 核心引用 | `Problem`、`Submission`、`User` | [已有核心表引用](./data-model-v1.md#4-已有核心表引用) |
| 知识图谱 | `KnowledgePoint`、`KnowledgeDependency`、`ProblemKnowledge` | [知识图谱表](./data-model-v1.md#5-知识图谱表) |
| 外部题目采集与导入 | `ProblemImportBatch`、`CollectedProblem`、`ExternalProblemBinding`、`ExternalTagMapping` | [外部题目采集与导入表](./data-model-v1.md#6-外部题目采集与导入表) |
| 教学班和教师权限 | `TeachingClass`、`TeachingClassTeacher`、`TeachingClassStudent` | [教学班结构](./data-model-v1.md#65-teaching_class) |
| Elo 与学习路径 | `StudentKnowledgeState`、`ProblemKnowledgeRating`、`RatingHistory`、`LearningPath`、`LearningPathStep` | [Elo 与学习路径表](./data-model-v1.md#7-elo-与学习路径表) |
| RAG | `RagDocument`、`RagChunk` | [RAG 数据表](./data-model-v1.md#8-rag-数据表) |
| Agent | `AgentRun`、`AgentToolCall`、`ErrorPattern`、`AgentConversation`、`AgentMessage`、`AiFeedbackReview` | [Agent 数据表](./data-model-v1.md#9-agent-数据表) |

第一期优先实现知识点、题目知识点映射、题目导入、外部题目绑定、标签映射、教学班权限、Agent 运行审计、错误模式和结果反馈。Elo、学习路径、RAG 和复杂多轮会话的结构同时冻结，但允许延后启用。

## 3. 冻结的数据原则

### 3.1 兼容现有 OJ

- 不替换现有 `Problem`、`Submission` 和 `User` 主键语义。
- Agent、知识图谱、Elo 和 RAG 通过扩展表关联现有业务数据。
- 初始迁移不批量改写现有题目标签和历史提交。

### 3.2 标识和唯一性

- 内部关联使用数据库主键；对外接口使用文档明确的稳定标识。
- 外部题目以来源平台和来源题号建立稳定绑定。
- 批次内 `problem_key` 以及 `source_platform + source_id` 必须唯一。
- Agent Run、导入批次、学习路径和向量片段保留版本及追溯信息。

### 3.3 删除与审计

- 核心业务真相和审计记录优先使用 `PROTECT` 或软删除。
- 只属于父记录的纯子记录可以 `CASCADE`。
- 历史记录允许外部对象删除后保留快照或置空引用。
- Agent 调用、题目来源、Elo 变更、导入问题和教师访问边界必须可追溯。

### 3.4 数据归属和权限

- Agent 只读取领域服务提供的数据，不直接成为业务真相的写入者。
- 教师身份来自活动教学班成员关系，不等同于全站管理员。
- 教师只能读取其活动班级中活动学生成员的数据。
- 未审核的题目映射、错误模式和 RAG 文档不能进入学生端 Agent 上下文。
- 学生代码、隐藏测试点、标准答案和敏感字段不得进入通用日志或向量库。

## 4. 机器数据契约附件

| 附件 | 校验对象 | 用途 |
|---|---|---|
| [collection-config-v1.schema.json](./schemas/collection-config-v1.schema.json) | 数据采集配置 | 约束来源、网络、合规和输出设置 |
| [problem-import-v1.schema.json](./schemas/problem-import-v1.schema.json) | 标准化题目记录 | 约束 JSONL 中每一条题目元数据 |
| [problem-testcase-manifest-v1.schema.json](./schemas/problem-testcase-manifest-v1.schema.json) | 测试数据清单 | 约束 ACM/OI 测试点、分值、路径和哈希 |
| [qduoj-problem-v1.schema.json](./schemas/qduoj-problem-v1.schema.json) | QDUOJ `problem.json` | 对齐现有题目导入序列化器 |
| [problem-batch-manifest-v1.schema.json](./schemas/problem-batch-manifest-v1.schema.json) | 批次 `manifest.json` | 约束题目目录、文件索引和完整性信息 |
| [problem-import-report-v1.schema.json](./schemas/problem-import-report-v1.schema.json) | 导入报告 | 约束批次汇总、逐题状态和问题列表 |

这些 Schema 均使用 JSON Schema Draft 2020-12，保留独立 `$id`，以便数据生产者、后端和测试工具分别引用。

## 5. 迁移和实现顺序

建议按以下依赖顺序落地，但实现不属于本阶段文档交付范围：

1. 知识点、依赖和题目知识点映射。
2. 题目导入批次、采集题目、外部绑定和标签映射。
3. 教学班、教师和学生成员关系。
4. Agent Run、工具调用、错误模式和反馈。
5. Elo 状态、评级历史和学习路径。
6. RAG 文档、片段和复杂会话。

## 6. 验收标准

“确定数据结构”任务满足以下条件即视为完成：

- 所有表的字段、类型、必填性、默认值和业务含义无待定项。
- 唯一约束、索引、外键删除策略、数据归属和教师权限边界已经定义。
- 六个 JSON Schema 可以被 Draft 2020-12 校验器解析。
- 正例通过，路径穿越、非法状态、错误分值等反例被拒绝。
- 数据结构与接口、批量交付契约使用一致的标识和枚举。

当前 1.0.0 版本满足上述文档与机器契约验收条件。冻结不代表 Django Model、Migration 或数据工作流已经实现。
