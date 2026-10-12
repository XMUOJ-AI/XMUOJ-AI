# 确认项整改与第二轮后端验收（2026-10-12）

**结论：获准的四项整改已完成，本轮覆盖范围内没有尚未修复且可复现的代码阻断；生产发布与原始全部需求验收仍不通过。** 后端407项和前端96项测试全部通过，实际镜像构建及隔离升级演练通过。

本轮承接[首轮完整验收](backend-acceptance-2026-10-12.md)。用户已授权整改比赛计分、AI 输出、依赖安全和插件 Session；新功能扩展及真实环境联调暂缓。对象仍为 `duduking19`，起点 `e5341ee`，保留上轮所有未提交修改；没有提交、推送或部署。

## 已实施的整改

| 顺序 | 首轮阻断 | 本轮处理与边界 |
| --- | --- | --- |
| 1 | D01 比赛重判无法可靠回退 | 以有效持久提交重建比赛排名、题目统计、用户逐题状态和参与记录。ACM 取首个 AC 与此前错误的20分钟罚时，CE 不罚时；OI 每题最高合法分数，AC 事实独立按真实终态统计。支持赛后重判、AC→WA、系统错误撤回、重复消息及不同提交并发结算。原提交与计分结果同事务，远程 Judge 调用不在锁内。 |
| 2 | D02 模型自报“无完整答案”不可信 | 学生输出默认自然语言提示与文字伪代码；共享检查器逐字段检查代码、常见编码及内部信息。发布、历史 GET、幂等重放、缓存复用、RAG 学生资料入库和历史检索都复检。保留正常变量名、复杂度、数学式与括注；不新增审核功能或未经审核代码豁免。 |
| 3 | D03 旧框架及服务器依赖风险 | 升级至 Django 5.2.18 LTS、DRF 3.18.3、Gunicorn 26.2.0、Pillow 12.3.0；Raven 替换为 sentry-sdk 2.71.0。同步路由、时区、索引迁移、运行文档和镜像依赖。删除与 Django 5 事务断连语义冲突的 django-dbconn-retry monkeypatch，回归确认事务中失联不会静默新建连接。 |
| 4 | D04 插件返回 token 却未建立可用身份 | 复用 Django Session：bootstrap 发 CSRF，登录轮换凭据，客户端保存 Cookie；写操作需当前 CSRF，退出注销当前 Session。兼容保留 SSO token，但不把它扩展成全站 Bearer 权限。停用账号、2FA、同号重登与换号均有回归。外部 VSCode 客户端不在仓库，需按[插件协议](../../backend/plugin/README.md)接入。 |

比赛有效提交限于：当前启用的普通用户、非创建者、当前可见且属于该比赛及规则类型的题目、原提交时间在比赛起止范围内、明确判题终态。PENDING、JUDGING、SYSTEM_ERROR 不计比赛分数；非法/缺失 OI 分数不虚构100分。进行中 ACM 冻结快照保留；结束后读实时重建排名。历史数据、身份变化或删除记录后使用 `python manage.py rebuild_contest_scores <contest_id>` 显式修正，不自动改写全部历史比赛。详见[计分说明](../learning-implementation-2026-10-07.md)。

Sentry 仅在生产环境显式配置 DSN 时启用；实际 SDK 的白名单事件测试确认请求、Cookie、代码、原始异常、局部变量和附件均不外发。本轮采用内存 transport 验证，没有连接真实 Sentry。

## 独立复核发现并补修

- **隐藏 OI 分数旁路**：手动校准接口仅检查登录和可见性，能读取进行中的隐藏成绩。现复用榜单权限，密码、开始时间及隐藏榜单校验在重算之前完成。
- **历史分数异常时状态不一致**：缺失或非法分数的 AC 加上70分部分正确，原新实现会显示70分但不同入口的 AC 事实不一致。现分数与 AC 事实独立计算，不补造分数。
- **参与时间污染**：重判和历史重建触发 `auto_now`，把计分更新写成新进入时间。现只更新计分字段，保留首末进入时间与次数。
- **AI 边界反例**：补拦完整多行 Python、无括号 Ruby 输出及编码的地址/路径/凭据；修复英文括注、条件等式和数学函数误拦。已识别的反例纳入回归。
- **历史 CI 凭据**：从 `.travis.yml` 移除硬编码 Slack 通知凭据；没有尝试调用它，也没有清写 Git 历史。是否仍有效需要凭据所有者确认。

## 实际验证

最终结果与命令、退出码见[证据目录](backend-remediation-evidence-2026-10-12/)。本轮所有数据库操作使用隔离 PostgreSQL/Redis 与合成数据，临时数据库完成后删除。

| 检查 | 最后有效结果 | 证据 |
| --- | --- | --- |
| 后端全量 `python manage.py test --settings=oj.settings --noinput` | **407项全部通过，测试82.016秒，进程退出码0**；含账号/题目/比赛/判题/知识/学习/导入/Agent/RAG及共享组件 | [日志](backend-remediation-evidence-2026-10-12/test-final.log)、[结果](backend-remediation-evidence-2026-10-12/test-final-result.json) |
| 后端 `flake8 --statistics .` | 退出码0，无输出 | [日志](backend-remediation-evidence-2026-10-12/backend-lint-final.log) |
| 旧 Django 3.2 schema/合成数据 → Django 5.2 迁移 | 旧密码可验证，用户/比赛/题目/提交代码/JSON/参与记录保留，索引正确改名；无迁移漂移、无待执行迁移 | [7步结果](backend-remediation-evidence-2026-10-12/upgrade-results.json)、[数据验证](backend-remediation-evidence-2026-10-12/upgrade-preservation.log)、[脚本](backend-remediation-evidence-2026-10-12/check_upgrade.py) |
| Node24 前端 `npm test` / `npm run lint` / `npm run build` | **21文件96项全过**；lint和构建退出码0；构建仍有既有chunk大小警告 | [结果](backend-remediation-evidence-2026-10-12/frontend-results.json)、[测试](backend-remediation-evidence-2026-10-12/frontend-tests.log)、[构建](backend-remediation-evidence-2026-10-12/frontend-build.log) |
| 工作契约、题包工具、部署检查、`pip check` | 契约通过、工具6项和部署11项全过、无依赖冲突 | [结果](backend-remediation-evidence-2026-10-12/auxiliary-results.json) |
| 原生产 Dockerfile 实际 BuildKit 构建 | Python3.12 Alpine与生产psycopg2源包安装成功；最终镜像重新纳入全部修复，465个后端和前端产物文件与工作区相同 | [依赖完整构建](backend-remediation-evidence-2026-10-12/image-build-buildkit.log)、[最终构建](backend-remediation-evidence-2026-10-12/image-build-result.json)、[源码比对](backend-remediation-evidence-2026-10-12/image-source-check.json) |
| 最终镜像 `pip check` / Django `check` | 禁用网络的临时容器内通过；使用合成secret；包集合与审计时一致 | [结果/镜像ID](backend-remediation-evidence-2026-10-12/image-check-result.json)、[日志](backend-remediation-evidence-2026-10-12/image-check-final.log) |
| `pip-audit` 扫描实际镜像安装的全部45个Python包 | **未发现已知漏洞，退出码0**；固定实际包名/版本，包含传递依赖；不涵盖Alpine系统包、Judge沙箱或前端包 | [清单](backend-remediation-evidence-2026-10-12/image-requirements.txt)、[原始结果](backend-remediation-evidence-2026-10-12/image-audit.json)、[日志](backend-remediation-evidence-2026-10-12/image-audit.log) |
| 新Gunicorn＋Django真实回环HTTP | 8项通过：bootstrap、强制CSRF、Session登录、拒旧CSRF、非法JSON根、CL/TE冲突、重复CL、退出 | [结果](backend-remediation-evidence-2026-10-12/http-results.json)、[脚本](backend-remediation-evidence-2026-10-12/check_http.py) |
| 两套Nginx上传配置 | 2项语法＋4项HTTP检查通过，HTML二进制、PNG类型及nosniff/sandbox均正确 | [结果](backend-remediation-evidence-2026-10-12/nginx-results.json) |
| 源码高置信凭据格式检查 | 467个文本文件，所选Slack webhook/AWS key/私钥格式无命中；不是全面秘密扫描 | [范围与结果](backend-remediation-evidence-2026-10-12/source-secret-check.json) |
| 临时库清理 | 本轮全量测试、升级演练和HTTP临时库均已删除 | [结果](backend-remediation-evidence-2026-10-12/database-cleanup.json) |

本机 Python 3.11 验收使用新建临时 venv，未覆盖项目原 `.venv`；本机缺少 `pg_config`，使用同版本 `psycopg2-binary==2.9.9`。实际 Python 3.12 Alpine 镜像按生产 requirements 编译安装 `psycopg2==2.9.9`，另检查镜像依赖与 Django 加载。两种环境的验证范围分别记录，不能混称为都执行了全库测试。

保留了过程失败：首次 Django 5 启动暴露被移除的 `index_together`，以显式索引和 RenameIndex 迁移修复；升级演练第一次合成夹具漏填 `real_time_rank`，仅修正夹具；首次 Docker legacy builder 不支持原 Dockerfile 的缓存挂载，改用本机已有 buildx 后构建原文件；首次 HTTP 探针受环境代理影响，改为明确直连回环地址。没有为通过测试放宽生产权限。

## 七类重点的复验结论

| 维度 | 本轮验证覆盖 | 保留边界 |
| --- | --- | --- |
| 空值 | JSON 根类型、模型输出嵌套/异常类型、缺失或非法 OI 分数及原有各模块校验 | 不是全部旧接口输入的形式化穷举 |
| 重复 | 幂等回放、缓存重验、重复判题、重复重判和参与记录重建 | 新提交 POST 仍按原契约产生新 attempt，没有引入提交幂等键 |
| 并发 | 数据库比赛锁、独立提交并发结算、既有 outbox/Session/限流/导入并发回归 | 外部 Judge 至少一次执行；大比赛全量重建需安排窗口，未承诺容量 SLA |
| 权限 | Session/CSRF、停用/2FA/账号切换、隐藏 OI/密码/时窗及原对象权限回归 | 外部插件客户端未真实联调 |
| 超时 | 原有 HTTP 慢头/慢体、Redis、SMTP、Agent 预算与恢复回归 | 未把同步系统 DNS 等阶段声称为严格墙钟中断 |
| 异常 | 计分与判题事务回滚、异常状态撤回、原导入补偿、任务恢复及依赖兼容 | 明确失败仍可能需要排障后显式恢复 |
| 泄露 | 输出与历史缓存复查、Unicode/HTML 规范化、Sentry 白名单及原响应脱敏回归 | 规则不能证明任意语言/混淆绝无代码或语义答案；真实教学内容质量未验收 |

## 剩余阻断与暂缓项

1. **生产发布/试点验收仍阻断**：真实 Judge、模型/Embedding/Milvus、实际插件、生产域名/TLS、数据库与文件一致性恢复尚未按本次代码复验。历史容量记录的建议延迟阈值未达标；目标机器、班级规模与 SLA 未确认。本轮遵照用户要求暂缓，不以单测或构建通过替代。
2. **原始完整需求仍有范围缺口**：教师高频错题/难度偏差/AI效果分析及教学开关、近期复盘、跨平台采集/相似检测等新功能未纳入本轮，按用户要求暂缓；当前工作契约实现不等于原始需求全部完成。
3. **凭据所有权待核实**：已删除历史 CI 配置中的 Slack 凭据。如果仍有效，须由所有者撤销或轮换；仅删除工作区引用不能使历史凭据失效。这是待人工核实事项，不宣称已确认泄露了现用凭据。

上线前需备份数据库和文件，停止旧 web/worker 写入并等待在途判题结束，迁移 `judge.0001` 与 `contest.0014` 后启动新进程及恢复器；不得混跑旧槽位机制的 worker。历史受影响比赛按 ID 显式重建。不得直接用旧 Django 代码读取含新迁移的状态作为“无损回退”；回退方案需在目标环境单独演练。以上为交付要求，本轮未执行生产操作。

依赖选择参考官方资料：[Django 支持版本](https://www.djangoproject.com/download/)、[DRF 发布记录](https://www.django-rest-framework.org/community/release-notes/)、[Gunicorn](https://pypi.org/project/gunicorn/)、[Pillow](https://pypi.org/project/pillow/)、[Sentry SDK](https://pypi.org/project/sentry-sdk/2.71.0/)。Django 5.2 LTS 的扩展支持至2028年4月；扫描无已知漏洞是当时数据库和所列包范围的结果，不是永久安全保证。
