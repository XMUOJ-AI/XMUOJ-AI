# 2026-10-12 验收证据

结论与范围见[完整报告](../backend-acceptance-2026-10-12.md)，机器可读结果见 [summary.json](summary.json)。所有文件均来自本轮执行，未复制数据库凭据、真实用户资料、密钥或配置备份。

- `baseline*`：整改前 318 项，其中 ZIP 时间戳夹具导致 1 error。
- `round-one.txt`、`*-before.json`：首轮只读问题摘要，以及限流、越界清理与异常日志反例；使用合成数据和临时目录。
- `test-final*`：第一次整改后 378 项、2 处旧测试假设失效的记录。
- `test-final-fixed*`：最终 379 项全部通过；进程退出码、实际命令与耗时一并保留。
- `test-judge*`：判题/提交/配置/HTTP deadline 的 55 项定向结果，时间早于插件补例；最终全库才包含插件补例。
- `fresh-migrate.log`、`migration-*.log/json`、`system-check.log`：独立临时空库的正向迁移、漂移和系统检查，不是生产恢复演练。
- `frontend-*`：Node 24 的测试、lint 和构建；build 中保留 chunk 警告。
- `contracts.log`、`problem-batch-tools.log`、`deploy-tests.log`：工作契约、题包工具和部署单测。
- `nginx-results.json`、`check_nginx.py`：两套配置的实际 nginx 语法和 HTTP 内容类型/安全头检查；脚本依赖本轮隔离 Docker context。

测试中预期的 403/503、人工异常注入等日志不能单独解释为测试失败，以末尾 unittest 汇总及退出码为准。Django 测试在独立 PostgreSQL/Redis 实例运行，使用自动建立并销毁的 `test_xmuoj_acceptance_20261012`；迁移临时库也已删除。数据库测试始终串行，不与子代理争用共享 Redis。

复跑需要按项目运行文档配置隔离 PostgreSQL/Redis，并从报告表格指定目录执行命令。不要将此测试库名指向业务数据库。此前原样停止的 `default`/`xmuoj` Colima profile 未启动；本次临时启用的 `xmuoj-merge-20261011` 在交付前停止，保留已有卷与镜像。
