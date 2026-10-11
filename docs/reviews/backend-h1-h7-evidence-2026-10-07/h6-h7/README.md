# H6 / H7 镜像与真实链路验收

## 环境与边界

验收使用隔离数据库 `xmuoj_h7`、独立 Docker 网络 `xmuoj-h7-20261007` 和同名前缀容器/数据卷，不使用已有应用数据库或测试用例卷。目标镜像为 `linux/amd64`；本机 Colima 通过 QEMU 运行，不能以此代替生产原生架构容量验收。

前端 DLL 与生产构建通过；完整 `--no-cache` 镜像构建成功，见[从零构建日志](../build/image-clean-build.txt)。心跳修复后又完成[最终源码构建](../build/image-heartbeat-final-build.txt)，并逐项核对镜像内270份生产源文件，[全部一致](image-source-check.json)。这次后续构建复用了依赖层，不冒称再次从零安装。前端全量 lint 的334项历史错误均位于本轮未修改文件，见[基线对照](../build/frontend-lint-baseline.json)；本轮前端文件定向检查通过。

本地证书是仅含 localhost / 127.0.0.1 的隔离验收证书；requests实际校验证书，没有使用跳过验证。测试账号、Judge Token随机生成，保存在仓库忽略的 `.venv/h7-runtime/` 私有配置文件；不记录密码、凭据XLSX或Token。客户端证书与正式域名证书链不是同一项验收。

真实 JudgeServer 使用 `registry.cn-hongkong.aliyuncs.com/oj-image/judge:1.6.1`，独立 `/judger`、`/log`、`/test_case` 卷。判题经真实HTTP、Redis/Dramatiq与代码执行RPC，不用Judge替身；A+B输入输出是本轮自己构造的测试数据。

## 首次失败与修复

首次HTTPS、账号与导出流程通过，但判题一直为PENDING。真实冷启动的并发心跳注册了两条相同hostname，之后 `.get()` 抛出 `MultipleObjectsReturned`。失败检查与原始异常分别保存在[first-failure-runtime-results.json](first-failure-runtime-results.json)、[心跳异常](first-failure-heartbeat-trace.txt)，没有覆盖删除失败证据。

新增主机名唯一约束、并发安全 `update_or_create` 和 `conf.0005` 迁移；仅合并每条占用计数都为零的重复组。任何非零计数均拒绝并回滚，以保留按原主键释放任务的语义。[维护边界](../../../judge-server-heartbeat-migration.md)。PostgreSQL conf回归23项、强化迁移边界2项通过；见[回归](heartbeat-after.txt)、[迁移边界](heartbeat-migration-boundaries.txt)。最终容器已通过自动迁移处理原有重复组，没有手工删行绕过缺陷。

## 实际验证

- HTTPS配置及健康检查11项单元测试通过。实际Alpine镜像 `nginx -t` 退出0；既有 `listen ... http2` 弃用提示不影响语法通过。
- 真实直连TLS已验证HTTP跳转、HSTS、HTML/静态资源、安全Cookie与CSRF；账号验证覆盖随机初始密码登录、创建者导出重试与学生越权拒绝。
- [7项代理边界检查](proxy-results.json)通过：不可信来源伪造协议/IP头不能绕过跳转；可信来源仅小写 `https` 被接受；大写、逗号多值和HTTP均跳转；恢复实际客户端IP；合法心跳结构缺Token被拒绝。测试后恢复direct模式。
- 最终镜像[20项运行检查](runtime-results.json)全部通过：真实Python3提交AC、Dramatiq更新画像、重判不重复计数、Judge离线时等待、重启后自动判题与画像更新、推荐路径生成，以及私有凭据0700/0600权限和后台到期清理。缺模型返回503仅属错误处理检查。
- [心跳现场数据](heartbeat-runtime-summary.json)确认最终只有1条主机记录、无重复hostname、占用计数归零。[最终启动日志](final-container-startup.txt)记录conf.0005自动迁移成功；[镜像信息](image-runtime-metadata.json)记录实际镜像与容器ID。
- 中途验收脚本将重判请求误写为 `/api/admin/submission`；对照路由改为 `/api/admin/submission/rejudge` 后重跑，未为此改动生产接口。中间记录保存在 `probe-route-error-*`，最终20项使用修正后的脚本。

## 重现与剩余输入

[scripts/](scripts/)保存本次实际使用的脚本。若重跑，应把其中内容复制回仓库根目录 `.venv/h7-runtime/`；脚本按该路径定位仓库，证书/私有env由setup生成，不随证据提交。需要Docker、项目虚拟环境、已有隔离测试PostgreSQL容器（端口15432）和上述两个本地镜像。setup不会替换已有容器；升级镜像需先停止并移除本轮同名前缀backend容器，保留卷后再创建。禁止将这些固定测试库名/容器名改为实际业务环境直接执行。

真实模型、Embedding、Milvus的服务配置、审核语料，以及生产域名和TLS终止位置未提供。[配置存在性](external-config-presence.json)只记录是否配置，不读取或输出密钥。本地缺配置503只能证明错误处理，不能证明外部服务联通。新配置到位后仍需真实四类Agent、向量检索、超时/恢复和权限撤回联调。

验收结束后已停止本轮backend、Judge、Redis三个应用容器，保留镜像、数据库及卷；已有应用容器未改动。需要续跑时先启动本轮Redis与backend，待backend就绪后启动本轮Judge。验收证书仅有效两天，过期后应重新生成本地证书，不关闭客户端证书校验。
