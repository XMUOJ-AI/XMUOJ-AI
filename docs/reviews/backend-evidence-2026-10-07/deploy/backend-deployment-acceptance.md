# 后端部署验收入口（2026-10-07）

部署修复与隔离运行验证已完成。本文和相邻 `.txt` 归档既有证据；本轮归档未重新运行测试、启动容器或修改源码。没有部署生产，也未修改旧服务或旧数据库。

## 验证结果

| 项目 | 结果与证据 |
| --- | --- |
| 健康检查 | **8 个定向回归通过**，覆盖正常响应、进程正常但 HTTP 不可达/超时、异常状态/响应及 Supervisor 故障；使用无代理的本地探测，失败不输出响应体或 traceback。[原始测试输出](health-tests.txt)；这是总体测试启动后新增的独立验证，不冒充已包含在该轮全库结果中。 |
| 管理员初始化 | **4 个 Bootstrap 用例**分别在 Python 3.11 与 3.12、真实 PostgreSQL 中通过；同一组用例不重复计数。[Python 3.11](bootstrap-python311.txt)、[Python 3.12](python312-check-bootstrap.txt)。 |
| Python 3.12 Alpine | 旧 x86 镜像实测 Python 3.12.13、Django 3.2.25；当前 requirements 的直接固定版本全部匹配，完整源码 `manage.py check`、`pip check` 通过，测试空库迁移成功。[运行时版本](runtime-version-permissions-transcript.txt)、[版本匹配记录](requirements-first-attempt.txt)、[检查与回归](python312-check-bootstrap.txt)。 |
| 真实服务与 HTTP | Supervisor 六进程实际启动；冷启动未完成时新健康检查返回 **1**，服务就绪后返回 **0**；设置不可达代理环境变量仍能完成本地探测。经 Nginx 访问新知识 API 返回预期未登录 **401**。[启动与停止](supervisor-start-stop.txt)、[未就绪](health-not-ready.txt)、[就绪](health-ready.txt)。 |
| 权限与队列 | `server` 实际 UID 900/GID 903，成功创建 0700 私有题包目录及写入测试点目录；测试目录根为 710、密钥文件为 600。自动发现 `default`、`agent`、`problem_import` 队列。[权限与队列断言](worker-permissions-queues.txt)、[实际文件权限](runtime-version-permissions-transcript.txt)。 |
| 自动恢复 | 故意绕过 `post_save` 写入一条终态提交；独立恢复进程补建事件，真实 Redis/Dramatiq worker 将其处理为 `processed`、revision=processed_revision=1，重复投递被正常确认。Agent、Import 恢复进程也实际周期运行，此次无待恢复任务。[状态断言](state-assertions.txt)、[Learning 恢复](runtime-recover-learning.txt)、[Worker](runtime-dramatiq.txt)、[Agent 恢复](runtime-recover-agent.txt)、[Import 恢复](runtime-recover-import.txt)。 |
| Sentry | 未配置 `SENTRY_DSN` 时，Raven app、配置 handler 和实际 logging handler 均不存在；显式配置时三者启用且配置值匹配输入，未输出值。[两种运行状态](sentry-assertions.txt)。 |

版本匹配记录后半段保留了首次审查脚本误用 Django 小写 settings 属性导致的错误；这是审查脚本错误，非应用故障。修正后的 Sentry 两种运行状态另有独立通过记录，未隐藏该首次失败。

## 三类启动分支

1. **迁移失败**：实际 shell 入口的故障注入验证连续失败 5 次后退出 1，未启动 Supervisor；迁移命令使用固定失败替身，不能当作真实 SQL 迁移失败测试。[工具原始输出节选及方法](migration-failure-transcript.txt)。
2. **空库首次初始化**：真实 PostgreSQL 全量迁移后，未提供 `DJANGO_SUPERUSER_PASSWORD` 时拒绝启动；随后通过环境提供密码，实际创建管理员并启动六个服务。[缺密码分支](empty-bootstrap.txt)、[正常首次启动](supervisor-start-stop.txt)。密码不进入初始化命令参数或日志。
3. **已有管理员库**：不提供初始化密码时完整启动前置流程通过，账号数量和密码哈希保持不变；未提供新的判题 token 时原值保持不变。此轮最后的 Supervisor `exec` 使用标记替身，避免运行中的审查环境启动第二个守护进程。[已有库流程](existing-bootstrap.txt)、[状态比对](state-assertions.txt)。包含引号的测试 token 已验证原样写入，归档不包含其值。

## 运行边界与清理

- 本次使用**已有 x86 镜像，离线补齐新增依赖并复制当前源码进入临时容器**，并非从零构建生产镜像。当前仓库缺少 `frontend/dist/`，未执行完整 Docker build；前端生产构建与整镜像构建仍需按仓库入口单独验证。
- ARM 主机运行 x86 镜像的 QEMU 并发冷启动触发了 Gunicorn 默认 30 秒 worker 超时。[失败记录](runtime-gunicorn.txt)。仅审查容器使用 `MAX_WORKER_NUM=1`、`GUNICORN_CMD_ARGS='--timeout 180'` 完成验证；生产配置仍保留默认 **30 秒**，没有把仿真预算写入源码。慢速部署环境可经现有 `GUNICORN_CMD_ARGS` 环境变量调整启动预算，但应测量实际启动/请求耗时后配置，不能把本次模拟环境结果当作生产性能结论。
- 使用专用审查数据库与独立 Redis 16380，未消费共享测试 Redis 16379 的消息。六个 Supervisor 进程已正常关闭；主要审查容器已停止并保留，16380 Redis 按原 `--rm` 一次性配置停止后自动删除。[清理结果](cleanup.txt)、[完整停止记录](supervisor-start-stop.txt)。
- 只归档必要文本日志。密码哈希快照、含测试凭据的脚本及环境值没有复制；配置密码、token、DSN 值不在归档中。
