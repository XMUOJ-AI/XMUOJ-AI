# 本地优先合并记录（2026-10-11）

## 来源和工作区状态

- 本地分支：`duduking19`，原 Git 基线 `144410a5a1847afa443f6ee609e13fdc256e187d`，开发内容原本未提交。
- 实际核对的远端 `main` 仍为 `144410a`；本次吸收 `origin/shiyuan@6d969e6bed358e0ef1409c99a7409496918364e8`。
- `origin/fuyue/tab@47cbeff15e2571b32c03af21a023ec50891a5074` 是 `shiyuan` 的祖先，其 Vue 3/Vite 与 AI 原型变更一并包含。
- 合并前备份：工作区上级 `资料归档/2026-10-11/合并前-191816/`。归档包含737个源码/文档文件及 `.git`，并保存原始差异、状态和 SHA-256 清单。被忽略的虚拟环境、运行数据及本地密钥没有纳入源码归档，也没有因合并被删除。
- 以共同基线进行文件三方合并，并人工处理冲突和接口差异。合并完成时保留原分支及未提交工作区状态；用户随后授权提交并推送至远端 `duduking19`。本次提交保留该源码整合结果，未合并远端 PR 或部署；远端源码来源以上述 commit 为准。

## 保留与吸收

| 范围 | 处理结果 |
| --- | --- |
| 本地后端 | 保留 knowledge、learning、problem_import、rag、agent_service 全部实现及迁移链；保留判题结算、并发与历史保护、Session/CSRF、私有凭据导出、HTTPS、任务恢复及既有修复 |
| 重复知识后端 | 不引入远端另一套模型/services/0001；不引入会遮蔽本地 `knowledge/urls.py` 的 `knowledge/urls/` 包，也不添加依赖另一套服务的 admin/api/public 文件 |
| 独立后端修复 | 吸收版本信息按 `BASE_DIR` 读取 UTF-8 文件的修复，新增非 backend 工作目录回归；合入远端 `redis==5.0.8`，保留本地 jsonschema 依赖 |
| 前端基础 | 吸收 Vue 3、Router 4、Vuex 4、Vite、View UI Plus、Element Plus、Node 24、npm锁文件、对应测试和部署入口；移除旧Webpack/DLL构建链 |
| 本地前端功能 | 移植随机密码说明、16位密码默认值、私有凭据列表和Blob下载，适配Vue3插槽；保留POST重判和教师画像审计头工具 |
| 知识页面 | 吸收远端主站/管理端页面；兼容本地大集合分页、管理详情分页、默认pending审核、历史快照、审核权限、冲突输入恢复及旧异步请求隔离 |
| 学习与AI | 保留远端Mock原型；生产页面接入本地真实服务，详见下表 |
| 文档与辅助脚本 | 合入远端前端说明、Windows开发脚本、人工测试清单；保留本地历史资料，标明原型契约与当前实现的区别 |

未吸收远端空的根目录 `package-lock.json`（无根 package.json、无依赖），前端使用自己的完整锁文件。未引入会设置固定密码/超级管理员且依赖另一套模型的 `seed_knowledge_demo`；人工验收清单已注明其不适用于合并后的本地服务。

## 生产页面与本地服务

| 页面 | 当前服务与行为 |
| --- | --- |
| 学习路径 | `GET /api/recommendation/path`、主动 `POST /api/recommendation/refresh`；保留服务端给出的题目、顺序、推荐理由与进度；旧路径链接失效时明确提示，只提供当前活动路径 |
| 路径解释 | `/api/agent/v1/runs` 的 `learning_path_explanation`，引用现有 `path_id` |
| 提交代码解读 | 同一Agent运行接口的 `code_explanation`，使用本人的提交ID；服务器继续校验所有权、题目可见性与判题快照 |
| 解题引导 | `/api/agent/v1/conversations` 与 `socratic_hint` 运行；使用展示题号，服务端控制180秒思考时间、三级提示、资料与额度；比赛题明确暂不支持 |
| 近期学习反馈 | 远端只有Mock聚合协议，本地没有对应的近期复盘服务；生产页面明确“尚未开放”，并提供学习路径入口，避免请求不存在的URL；单次提交反馈没有被冒充为近期聚合 |

Agent生成由用户点击触发，发送CSRF和幂等键，按 `run_id` 有界轮询，账号/上下文切换丢弃迟到结果；渲染真实结构化结果，不制造AI回答。后端未配置模型或服务不可用时显示明确错误。Mock与生产接口分别选择，生产产物应通过无Mock夹具检查。

## 验证

| 实际检查 | 结果 |
| --- | --- |
| 后端完整Django回归 | **318项通过**，43.123秒，退出0；[日志](local-first-merge-evidence-2026-10-11/backend-tests.log) |
| 后端flake8 | 退出0；[日志](local-first-merge-evidence-2026-10-11/backend-flake8.log) |
| 迁移漂移 | `No changes detected`，退出0；[日志](local-first-merge-evidence-2026-10-11/backend-migrations.log) |
| 前端完整Vitest回归 | **20个文件、92项通过**，退出0；[日志](local-first-merge-evidence-2026-10-11/frontend-final-tests.log) |
| 前端ESLint | 退出0；[日志](local-first-merge-evidence-2026-10-11/frontend-final-lint.log) |
| 前端生产构建 | 退出0，生成 `frontend/dist/`；保留上游大bundle提示；[日志](local-first-merge-evidence-2026-10-11/frontend-final-build.log) |
| 生产产物检查 | 学生/管理双入口、88个资源及字体引用通过，无Mock夹具或Vue2 DLL；[日志](local-first-merge-evidence-2026-10-11/frontend-production-artifacts.log) |
| 导入工具及契约 | `validate_contracts.py`通过；工具unittest **6项通过** |
| 浏览器冒烟 | 在 `127.0.0.1:18081` 的Mock模式验证首页、知识列表、选中BFS后图谱联动、知识详情及关联题目；读取浏览器error日志为空；不算真实模型联调 |
| 保留检查 | 本地五个新增后端模块共84个文件与备份SHA-256一致；后端只新增上述版本路径修复、回归和Redis版本固定；[核对记录](local-first-merge-evidence-2026-10-11/preservation-check.json) |

前端用 `npm ci --no-audit --no-fund` 安装远端锁文件，实际Node为24.21.0、npm为11.19.1；没有运行依赖安全审计。主机默认Node26，通过 `npm exec --yes --package=node@24 -- <命令>` 调用Node24执行上述检查。后端使用原 `.venv`，Redis客户端已对齐5.0.8。

后端检查运行于新建隔离profile `xmuoj-merge-20261011` 的 PostgreSQL14.23 Alpine/musl（`en_US.utf8`）和Redis7，数据库 `xmuoj_merge_20261011`、临时测试库 `test_xmuoj_merge_20261011`，未使用原开发数据库。检查后已停止profile，保留容器/测试卷；旧 `default`、`xmuoj` 始终停止。[环境与命令汇总](local-first-merge-evidence-2026-10-11/verification-summary.json)、[源码哈希](local-first-merge-evidence-2026-10-11/source-sha256.json)。凭据不收录在证据目录。

首次使用PostgreSQL14.24 Debian/glibc时，318项中有1项题号排序预期失败：相同 `en_US.utf8` 名称在glibc与原项目musl环境中的顺序不同（`other,P001` 与 `P001,other`）。已保留[首次失败](local-first-merge-evidence-2026-10-11/backend-tests-debian.log)和[SQL对比](local-first-merge-evidence-2026-10-11/sort-locale-debian.txt)，随后按历史环境对齐镜像后完整通过；未修改业务排序或测试预期。部署到不同libc/排序规则环境时，此差异仍存在。

## 限制

- 没有配置或调用真实外部模型、Embedding/Milvus供应商，接口/状态验证不代表模型效果验收。
- 本次没有执行Windows PowerShell脚本、生产镜像部署、真实判题服务器联调或生产数据迁移；历史H1–H7验收不计作本轮新执行结果。
- 若某外部环境已经应用远端另一套 `knowledge.0001_initial`，不能仅凭相同迁移名认定兼容；本次保留的是本地迁移链，未转换那些外部数据库。
- 原型版“近期学习反馈”的聚合后端仍不存在，Mock预览继续保留。
