# 题库批量导入

本应用接受 `docs/problem-import-contract-v1.md` 的正式 QDUOJ ZIP。JSONL 是采集与审计中间格式，先用仓库的 `tools/problem_batch/build_qduoj_batch.py` 转成 ZIP，再上传或运行命令。

## 管理端

全部端点要求启用且有题目权限的管理员 Session；写请求验证 CSRF。响应使用版本 `1.0.0` 的 `{error,data,request_id}` 包装。`Own` 管理员仅可查询和提交自己上传的批次；`All` 管理员和 `Super Admin` 可访问所有批次；`None` 普通管理员无导入权限。不存在或无权访问的批次统一返回 `404 IMPORT_NOT_FOUND`，详情、题目、错误和提交入口均适用。

- `POST /api/admin/problem-import/batches`：multipart `archive` 上传，返回 `202`，异步校验。
- `GET /api/admin/problem-import/batches/{batch_id}`：状态与汇总。
- `GET /api/admin/problem-import/batches/{batch_id}/problems`：题目分页；`status`、`limit`、不透明 `cursor`。
- `GET /api/admin/problem-import/batches/{batch_id}/errors`：错误与警告分页。
- `POST /api/admin/problem-import/batches/{batch_id}/commit`：必须带 `Idempotency-Key`，JSON 必须包含 `allow_partial`、`problem_ids`、`acknowledged_warning_codes`。

`problem_ids` 使用采集记录的整数 ID，空数组选择全部可导入记录。警告代码需先从报告读取并明确确认。指定子集时其余 ready 记录记为 skipped。重复幂等键返回原始接受响应；改变请求内容必须使用新键。运行时失败的记录可用新键重试，校验失败的原始内容不可强制导入。来源键唯一绑定已有题目，内容变化只保留 `IMPORT_SOURCE_UPDATED` 待审核记录。

ZIP 哈希和批次标识保持全局去重。重复上传只有在调用方可访问原批次时返回该批次，不转移上传人；命中其他上传人且无访问权限的批次，或同批次标识的不同数据包，均返回不含批次详情的 `409 IMPORT_BATCH_CONFLICT`。提交服务在事务和行锁内重新检查上传人权限，已有幂等结果也需通过当前授权。命令的 `--uploaded-by` 同样受这些权限约束。

## 命令与 worker

在 `backend/` 且数据库、Redis、secret.key 已配置时运行：

```bash
python manage.py rundramatiq
python manage.py import_collected_problems /path/to/batch.zip --dry-run --uploaded-by admin --report /path/to/report.json
python manage.py import_collected_problems /path/to/batch.zip --commit --uploaded-by admin \
  --acknowledge-warning IMPORT_KNOWLEDGE_CANDIDATE_INCOMPLETE \
  --acknowledge-warning IMPORT_REVIEW_REQUIRED \
  --acknowledge-warning IMPORT_TAG_MAPPING_PENDING
python manage.py recover_problem_imports --age-seconds 3600
```

实际警告以报告为准；未知或歧义标签还需确认 `IMPORT_TAG_UNRESOLVED`。命令支持 `--allow-partial`、`--batch-id`；退出码为成功 `0`、数据或部分失败 `1`、参数/文件/安全/环境错误 `2`。命令同步完成校验与提交，不依赖 worker。

异步 actor 使用 `problem_import` 队列，单任务上限 30 分钟、基础设施重试最多 3 次。恢复命令跳过正在运行的 worker，重启未完成校验；对中断导入按来源绑定核对并仅清理记录已分配、且无 Problem 引用的测试目录。运行时失败批次可再次提交新幂等键。

## 数据与安全边界

- Web ZIP 上限 256 MiB/500 题，命令上限 2 GiB/5000 题；JSONL 逐行限制 2 MiB，测试文件 64 MiB、单题测试数据 512 MiB。额外的解压安全上限为 2 GiB、单文件压缩比 1000，最大 100000 条目。
- 上传在 multipart 流阶段和受控存储阶段双重计数。拒绝路径穿越、重复路径、链接、特殊/可执行/加密文件、未声明文件、哈希不一致、非 UTF-8/LF 文本。所有声明 Schema 严格校验，包括未知字段。
- 默认存储为 `DATA_DIR/config/problem_import`，可用 `PROBLEM_IMPORT_DIR` 覆盖。归档不从 API 暴露；媒体只保留在隔离归档，不自动发布。测试 `info` 由后端重建，下载关闭，不运行 SPJ 或参考代码。
- 导入题始终 `visible=False`，只关联已存在的无歧义 active 标签。CSV 新映射只登记 pending，不覆盖旧映射。
- 1.0.0 `knowledge_candidates` 仅允许名称字符串，缺少 role/weight，因此完整保存并警告，不推断审核字段，不写正式 `ProblemKnowledge` 或不完整的 `KnowledgeMappingBatch`。人工补齐后使用知识模块的正式候选提交与审核入口。
- 默认整批数据库原子；`allow_partial` 逐题提交。文件先在测试根目录下暂存，题目事务内原子移动；数据库回滚后仅清理本批次的显式分配目录。PostgreSQL 会话锁防止重复 worker 与恢复任务交叉执行，来源事务锁和数据库唯一约束阻止重复建题。

## 验证

```bash
python manage.py test problem_import --settings=oj.settings
flake8 problem_import --statistics
```

测试需要真实 PostgreSQL 和 Redis，使用真实黄金包，覆盖恶意 ZIP、Schema/hash、权限/CSRF、上传流限制、重试、并发来源、文件补偿及真实 Dramatiq worker。
