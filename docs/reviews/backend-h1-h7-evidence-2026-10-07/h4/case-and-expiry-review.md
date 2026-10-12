# H4 独立复核后的用户名与凭据清理修正

2026-10-07。本记录补充原 H4 账号交付验证；不替代 H1 性能或全库验收。保留历史账号、权限和密码，不批量重命名历史数据。前端没有改动。

## 用户名登录等价性

复核发现导入的重复校验和已有账号查询使用大小写敏感的字符串/`username__in`，生成账号也直接写入前后缀；登录却通过 `UserManager.get_by_natural_key()` 使用 `username__iexact`。这是旧创建逻辑遗留、仍影响新随机凭据交付链路的缺口。

原实现的最小复现：在隔离测试库导入 `[["StudentA", "甲", "A"], ["studenta", "乙", "A"]]`；两项原始字符串不同，PostgreSQL 的普通 `username` 唯一约束允许写入。随后 `User.objects.get(username__iexact="studenta")` 匹配两项并抛出 `MultipleObjectsReturned`，因此两份已交付密码都无法通过正常登录定位唯一账号。已有 `StudentA` 后再次导入 `studenta`，或者生成前缀大小写变化，也会产生同类问题。此原路径为源码复核结论，没有把它写成已执行的旧版数据库回归。

当前实现：

- 新账号用户名及生成前后缀按项目现行规则转为小写，再校验长度；历史单个混合大小写账号保留原用户名与密码，导入仅更新其班级。
- 查询使用与 Django PostgreSQL `iexact` 相同的数据库 `UPPER` 规则。候选批次的登录等价重复全部拒绝；历史已经存在多个等价账号时明确拒绝，包含原回执重放，不猜测身份。
- 重试摘要使用规范化内容；相同大小写变体可找回同一凭据。仍接受完全相同原始请求的旧摘要，以恢复修复前已生成的有效回执。
- 两种批量入口共用事务 advisory lock，先锁创建域再锁创建者及已有用户，覆盖不同管理员同时创建尚不存在的等价名字。不会依靠大小写敏感唯一约束兜底这种竞态。锁沿用项目公共实现的5秒等待上限；超时会失败回滚，客户端可重试。此实现有意串行化管理端批量创建，未声称多管理员批量吞吐提高。

## 文件时间与回执有效期

原清理函数删除数据库中已经到期的回执后，还把所有 `mtime <= now - 24h` 的 XLSX 当成孤立文件删除，没有检查有效回执。文件写入和刷盘先于 `expires_at = timezone.now() + 24h`，所以两者存在正常的时间差。

原最小复现已经执行，使用从原文件 AST 提取的未修改 `cleanup_expired_exports()`、临时目录和空的到期查询替身，没有数据库或容器访问：设置文件 `mtime = now - 24h - 100ms`，有效回执 `expires_at = now + 100ms`。输出为 `receipt_live: true, file_exists_after_cleanup: false`。此结果只证明清理边界，不是完整 HTTP/数据库回归。

当前仅对真正没有回执的旧文件应用 mtime 孤立清理；仍有效回执对应文件保留。真正到期回执和文件仍由第一段清理，下载仍按数据库到期时间拒绝。

## 回归证据

新增8项检查覆盖：规范化新账号并实际下载/登录；历史混合大小写账号保留密码；同批等价重复与历史歧义拒绝；大小写变体重试；生成冲突；两个管理员并发导入/生成；旧mtime但回执有效时仍可下载。原有过期/孤立清理及写盘失败回滚检查继续运行。

运行命令（工作目录 `backend/`）：

```sh
POSTGRES_DB=xmuoj_h5 POSTGRES_PORT=15432 REDIS_PORT=16379 ../.venv/bin/python manage.py test account --settings=oj.settings --noinput --keepdb
../.venv/bin/flake8 account/views/admin.py account/credential_exports.py account/tests.py --statistics
```

账号完整80项回归通过，73.293s，原始输出：[account-case-and-expiry-tests.txt](account-case-and-expiry-tests.txt)。上述三个修改文件的flake8退出0、无输出，见 [account-case-and-expiry-lint.txt](account-case-and-expiry-lint.txt)。没有模型变更或新迁移。该轮使用专用 `test_xmuoj_h5`，没有操作 H1 数据库；采样窗口经 H1 负责人协调暂停，测试结束已关闭连接并释放资源。
