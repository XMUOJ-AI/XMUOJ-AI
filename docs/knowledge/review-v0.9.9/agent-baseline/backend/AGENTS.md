# 知识点模块后端 Agent 约束

## 生效前提

本文件必须放在实际后端 Git 仓库根目录后才生效。开始任何任务前，确认交付包已冻结为 1.0.0、上游数据模型变更已合入、README 已记录当前 40 位 commit，并且领取了一张 KP-DEV 任务卡。任一条件不满足时停止并报告。

## 权威顺序

已批准的数据模型与迁移高于 OpenAPI 和快照 Schema；OpenAPI 和快照 Schema 高于 PRD；PRD 高于任务卡。任何冲突都停止，不做猜测或双轨兼容。

## 修改边界

- 只修改当前任务卡列出的 knowledge app、测试、迁移和必要 URL include。
- 不修改 Problem、Submission、User 的既有字段、主键或语义。
- 不修改全局 APIView、JSONResponse、权限装饰器、登录、提交、判题或比赛逻辑。
- 知识模块新接口使用模块专用 KnowledgeAPIView；不得借任务重构全局响应层。
- 不新增或升级 Django、数据库、Python 包或系统依赖。

## 业务硬约束

- 正式 KnowledgeDependency 只保存当前生效边。create、update、delete 都先创建 KnowledgeDependencyChangeRequest；批准前正式边不变。
- 映射 batch_version 每次提交递增，approved_version 只在批准时递增，base_version 只引用 approved_version。
- 主站只读接口要求有效 Session，只返回 active 点、正式依赖和 visible 普通题的当前映射。
- 所有写请求校验 Session、CSRF、功能权限和对象权限。OWN 越界对象返回 404。
- 依赖变更和题目标注的提交人均不得 approve 或 reject 自己的申请。审核接口必须比较当前用户与 submitted_by；自审返回 403 `KNOWLEDGE_SELF_REVIEW_FORBIDDEN`，不得改变审核对象、正式数据或审计。
- 环检测、批准写入、映射集合替换和审计事件必须在事务中完成，不使用模型判断业务结果。

## 验证和报告

为每条业务规则提供正例和反例。先运行任务定向测试，再运行相关回归。最终报告列出实际变更文件、迁移影响、执行过的命令与真实结果、未解决风险。不得声称未运行的测试已通过。

## 必须停止

需要修改禁止目录、升级依赖、重写历史数据、改变旧接口语义、无法满足机器契约、缺少实际仓库 commit，或发现安全和敏感数据风险时立即停止并报告。
