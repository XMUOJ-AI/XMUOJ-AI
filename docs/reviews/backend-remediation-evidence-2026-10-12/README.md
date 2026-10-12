# 第二轮整改验收证据

关联[验收报告](../backend-remediation-2026-10-12.md)，对象 `duduking19` 未提交工作区。本目录保存实际日志和结果，不保存数据库凭据、本地secret或含历史凭据的原始diff。

- `test-final*`：最终407项Django全库回归；`frontend-*`：21文件96项、lint、构建。
- `upgrade-*`、`migration-*`：上轮Django3.2代码/schema到当前5.2迁移及合成数据保留。`*-first`为夹具失败历史。
- `image-build-buildkit.log`：完整生产依赖构建；`image-build-final*`：最终源码重建；`image-source-check.json`及`source-sha256.json`：465文件比对。
- `image-requirements.txt`：实际镜像安装的全部45个Python包；`image-audit*`：对此完整清单扫描，无已知漏洞。`audit-initial*`与`audit-final*`是本机验收环境升级前后记录，不替代镜像扫描。
- `image-check-*`：最终镜像禁网加载Django与依赖检查。`http-*`、`gunicorn-http*`：新Gunicorn真实回环HTTP、Session/CSRF与请求解析验证。
- `nginx-*`：本次两套上传安全配置的语法和HTTP检查；`auxiliary-results.json`汇总工作契约、题包工具、部署及pip检查。
- `backend-lint.log`是安全检查器编辑过程中的一次E128；最终以零输出的`backend-lint-final.log`为准。`image-build.log`记录legacy builder不支持缓存挂载，最终构建使用原Dockerfile和本机已有buildx。
- `database-cleanup.json`、`environment-stop.log`与`environment-final.json`：本轮临时库已删除、测试profile已停止；既有卷/镜像保留。

脚本保留实际执行路径，读取外部 `/tmp/xmuoj-merge-verification/test-env.json`（未附）。复跑时须使用独立数据库/Redis和合成密钥，按实际路径配置；数据库脚本遇到同名现存目标库会拒绝覆盖。升级演练的旧代码快照保留在本机 `/tmp/xmuoj-remediation-20261012/before-upgrade`，不是生产备份，也不是数据回滚证据。

全库日志中的403/503和异常类型来自负向用例；以退出码及407项的最终OK判断。未执行真实外部模型、目标容量、生产TLS、实际插件或数据库与文件完整恢复验收。此次本地镜像只用于构建与检查，没有部署应用。
