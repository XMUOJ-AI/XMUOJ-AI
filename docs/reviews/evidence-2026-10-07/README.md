# 契约审查复现附件

这些是文档审查证据，不是已实现 API 的测试报告，不属于原知识点交付包。

- [contract-check.py](contract-check.py)：只读新契约，构造合法响应和非法请求反例；包含纯图并发逻辑反例。
- [contract-check-results.json](contract-check-results.json)：2026-10-07 原始结果。
- [legacy-validation.txt](legacy-validation.txt)：旧题包 6 项测试与旧契约校验实际输出。
- [workspace-integrity.json](workspace-integrity.json)：归档 458 个文件、7 份原件、13 个交付文件、远端源码一致性和 89 条本地文档链接的检查结果。
- [requirements-validation.txt](requirements-validation.txt)：本次临时校验环境版本快照。校验环境为 Python 3.14.7；这不是后端业务运行环境的兼容性声明。

在仓库根执行以下命令可复现。依赖只装入临时虚拟环境，不修改后端依赖：

```bash
python3 -m venv /tmp/xmuoj-review-validation
/tmp/xmuoj-review-validation/bin/python -m pip install -r docs/reviews/evidence-2026-10-07/requirements-validation.txt
/tmp/xmuoj-review-validation/bin/python docs/reviews/evidence-2026-10-07/contract-check.py \
  --delivery-dir docs/knowledge/review-v0.9.9 \
  --output /tmp/xmuoj-contract-check-results.json
```

脚本的 `valid` 表示“该样本是否被当前 Schema 接受”，不是“该规则是否正确”。因此：

- 正常 null 响应和审核详情的 `valid=false` 是契约问题。
- create 缺字段、delete 带多余字段的 `valid=true` 表示机器约束不足。
- 零 primary 快照被接受只提示服务层仍须检查，不独立判定为缺陷。
- `endpoint_locks_disjoint=true`、各自无环而合并有环是图逻辑反例，没有连接 PostgreSQL。
- 脚本以正常退出表示证据已生成，**不表示契约整体通过**；应阅读结果和 [评审报告](../contract-review-2026-10-07.md)。

原知识包未被本次修正；后续应在明确版本的修订稿内解决问题，再运行实例验证。暂不把这个审查脚本当长期 CI 替代品。
