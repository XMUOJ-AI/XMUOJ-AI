# XMUOJ-AI 项目与后端文档

更新于 2026-10-07。代码基线为组织仓库的 `144410a5a1847afa443f6ee609e13fdc256e187d`。知识点模块以新包目标需求为准，但新包明确是 **0.9.9 评审稿，尚未冻结**；旧知识点模型不能直接作为实现依据。

## 当前开发入口

用户已授权暂缓评审排期并开始完整后端实施，代码位于 `duduking19` 分支。当前可执行工作契约在 `openapi/`、`schemas/`；原 ZIP 在归档中、原评审稿在 `knowledge/review-v0.9.9/`，均不因开发被改写或视为已签字。

- [后端开发与运行](backend-development.md)：环境、服务、数据准备及恢复入口。
- [开发后的当前任务清单](plans/backend-follow-up-2026-10-07.md)：已完成内容及真实联调、试点、冻结和发布的后续责任。
- [完整实现与验收矩阵](plans/backend-completion-matrix.md)：各模型、接口、工具及业务链路的实际证据。
- [2026-10-12 后端完整验收与整改](reviews/backend-acceptance-2026-10-12.md)：首轮权限、文件、并发、判题恢复及超时整改，以及当时的人工待决。
- [2026-10-12 确认项整改与第二轮验收](reviews/backend-remediation-2026-10-12.md)：比赛计分、AI 输出、依赖升级和插件 Session 的最新结果、证据与剩余阻断；功能扩展和真实环境联调暂缓。
- [Claude初次独立验收](reviews/claude-backend-acceptance-2026-10-07.md)：当轮有条件通过；3项修复、整改后271项全库回归及7项人工决策，不替代后续H1–H7验证。
- [工作契约修订说明](knowledge/implementation-notes-2026-10-07.md)：null、历史快照及新增查询闭环。
- [学习与班级实现](learning-implementation-2026-10-07.md)：算法参数、重判、班级权限及管理命令。
- [导入工作契约](problem-import-contract-v1.md)与[模块说明](../backend/problem_import/README.md)：题包、候选暂存和Own/All批次权限。
- [账号与临时凭据交付](account-import-credentials.md)：随机初始密码、大小写等价校验、归属及到期下载规则。

## 前期整理与评审记录

1. [后端负责人任务清单](plans/backend-task-list-2026-10-07.md)：本人的工作、协作边界、顺序和完成标准。
2. [契约评审报告](reviews/contract-review-2026-10-07.md)：已确认变化、实际缺口、待决事项及验证证据。
3. [文件整理记录](reviews/workspace-cleanup-2026-10-07.md)：代码基线、原件位置和未提交修改恢复入口。

## 项目范围原件

| 文件 | 用途 |
| --- | --- |
| [大创项目计划书](project/大创项目计划书.md) | 两项目总体目标与阶段；早期技术选项不等于当前定案 |
| [需求文档](project/需求文档.docx) | 工作流、RAG、四类 Agent、教学分析 |
| [技术路线与功能实现设计](project/技术路线与功能实现设计.docx) | Django/PostgreSQL、确定性工作流和受控 Agent |
| [系统设计参考案例](project/系统设计参考案例.pdf) | 参考方案，不是现行接口契约 |
| [题库扩容计划书](project/题库扩容计划书.pdf) | 采集、标准化、质量和数据交付 |

## 知识点最新评审输入

[review-v0.9.9/README.md](knowledge/review-v0.9.9/README.md) 及同目录文件均按新 ZIP **原样保留**，包括 PRD Markdown、人工评审 Word、前端原型、OpenAPI、快照 Schema、模型提案、差异归档和任务卡。`agent-baseline/` 是待整合的模板，未安装到实际代码目录。

原始需求输入为 [PRD v0.9.9](knowledge/review-v0.9.9/XMUOJ知识点体系模块PRD_v0.9.9.md) ；原包机器定义为 [knowledge-api-v1.yaml](knowledge/review-v0.9.9/knowledge-api-v1.yaml) 和 [快照 Schema](knowledge/review-v0.9.9/knowledge-snapshot-schema-v1.json)。本次问题另记评审报告，不静默改写原件。原包 Windows 路径不是当前代码基线。

## 第一期旧契约仍适用的范围

以下文件保留为采集、导入、学习、RAG、Agent 等后续设计基线。**知识点及跨模块引用正在变更，原文的“冻结”不表示已与 v0.9.9 对齐，更不代表接口已实现。**

| 入口 | 当前定位 |
| --- | --- |
| [data-structure-contract-v1.md](data-structure-contract-v1.md) | 旧结构总览，知识点内容待修订 |
| [interface-contract-v1.md](interface-contract-v1.md) | 旧 API 总览，不替代新知识点 API |
| [batch-data-delivery-v1.md](batch-data-delivery-v1.md) | JSONL 中间产物、QDUOJ-compatible ZIP 正式题包 |
| [data-model-v1.md](data-model-v1.md) | 旧模型；第 5 节及跨模块引用待联动评审 |
| [problem-import-contract-v1.md](problem-import-contract-v1.md) | 保留第一期题包基线；工作修订已明确候选暂存及批次权限，未审数据不写正式 ProblemKnowledge |
| [agent-tool-contract-v1.md](agent-tool-contract-v1.md) | 受控工具与 Agent 边界，后续实施依据 |
| [api-error-codes-v1.md](api-error-codes-v1.md)、[api-versioning-v1.md](api-versioning-v1.md)、[contract-change-policy-v1.md](contract-change-policy-v1.md) | 旧通用规则，知识模块差异须登记同步 |

机器附件保留在 [openapi/](openapi/) 与 [schemas/](schemas/)；黄金题包和展开样例保留在 [examples/](examples/)。它们承担不同验证用途，不是可删除的重复文件。

## 已有验证入口

在仓库根执行：

```bash
python3 -m unittest discover -s tools/problem_batch/tests -v
python3 -m venv /tmp/xmuoj-contract-venv
/tmp/xmuoj-contract-venv/bin/python -m pip install -r tools/problem_batch/requirements-contract.txt
/tmp/xmuoj-contract-venv/bin/python tools/problem_batch/validate_contracts.py
```

该验证器现覆盖 `openapi/` 中全部工作 OpenAPI、`schemas/` 中全部 JSON Schema 的结构及黄金题包；实际接口、并发与新知识快照由各 Django 模块测试覆盖。新包原件的反例和初次结果见 [审查附件](reviews/evidence-2026-10-07/README.md)。
