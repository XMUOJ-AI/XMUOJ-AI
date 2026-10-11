# H5 RAG 查询优化证据

修改范围为 `backend/rag/`；根任务补入标准 `django.contrib.postgres` AppConfig。没有连接生产库、真实 Embedding 或 Milvus。

## 已执行检查

- [完整 RAG 回归](tests.txt)：17 项，20.998 秒通过（原 13 项及新增 4 项）。覆盖实际 PostgreSQL、多语召回、英文多词排序/去重、同标题 UUID 次序、1/2/3 字中文和通配字符字面量、资料/资源作用域撤回，以及已有本地 HTTP 协议夹具。
- [迁移漂移检查](migration-check.txt)：`makemigrations --check --dry-run --settings=oj.settings` 输出 `No changes detected`，退出 0。
- RAG `flake8` 退出 0，无输出，原始输出文件为 [flake8.txt](flake8.txt)。
- [迁移 SQL](migration.sql)：`pg_trgm` 扩展、FTS/simple 表达式 GIN、`UPPER(content)` trigram GIN。测试库从迁移应用到最终回归均已实际执行。
- [初轮回归](tests-initial.txt)有 1 处失败：新增测试将无命中多词 `ts_rank` 的约 `1e-20` 要求为精确 0。修正为 15 位小数近似比较后完整重跑通过；没有修改生产评分算法。

## 性能复现

脚本 [benchmark.py](benchmark.py) 只接受 `xmuoj_h5:15432`，不会默认连接其他库。语料由脚本批量生成，以缩短装载时间；导入和清洗业务本身由上述功能测试覆盖。[corpus.json](corpus.json) 记录 20,000 份合成中英文课程讲义、100,000 个约 1,120 字符的 chunk、20 个知识点，每个知识点范围内 5,000 个 chunk，其中 50 个含指定检索词。标题重复；普通段落覆盖图、动态规划、排序、队列/栈、哈希。这是确定性合成资料，不代表真实学校语料分布。

PostgreSQL 14.23、`en_US.utf8`、`shared_buffers=128MB`；运行在本机 QEMU amd64 的 Colima VM，3 vCPU、4,100,120,576 bytes 内存，旧服务容器仍常驻。基准是回环连接下的顺序暖缓存 ORM 查询，排除 Embedding、Milvus、用户网络和并发负载，不是生产 SLA。

先建立数据库并只迁移到 `rag.0001_initial`（其余应用按正常最新迁移）。在仓库根目录设置下列环境并执行；环境均为本地隔离开发库，不是生产凭据。

```sh
export POSTGRES_DB=xmuoj_h5 POSTGRES_PORT=15432 REDIS_PORT=16379
.venv/bin/python docs/reviews/backend-h1-h7-evidence-2026-10-07/h5/rag/benchmark.py seed
.venv/bin/python docs/reviews/backend-h1-h7-evidence-2026-10-07/h5/rag/benchmark.py before --samples 3 --cases english_multiword chinese_three chinese_two chinese_one
.venv/bin/python backend/manage.py migrate rag --settings=oj.settings
.venv/bin/python docs/reviews/backend-h1-h7-evidence-2026-10-07/h5/rag/benchmark.py indexed --samples 1 --cases english_multiword chinese_three chinese_two chinese_one
.venv/bin/python docs/reviews/backend-h1-h7-evidence-2026-10-07/h5/rag/benchmark.py final --samples 15 --variants scoped_union --cases english_multiword chinese_three chinese_two chinese_one
```

每条检索 SQL 最多执行 30 秒；每种查询先预热一次。装载后及建索引后执行 `ANALYZE` 更新规划器统计，其维护超时单独设为 5 分钟。初次将索引后 `ANALYZE` 也限制为 30 秒时超时，见 [原始记录](analyze-initial-timeout.txt)；该次未进入采样，不计入性能结果。before 的 3 次样本只报告中位数和范围；indexed 的单样本用于探索三种查询形态及执行计划，不能当作稳定统计；final 的 15 次样本保留全部原始耗时。每个阶段均保存 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` 与参数展开后的 SQL。最后核对旧查询、候选合并查询以及实际 `search()` 的 chunk ID、顺序和分数完全相等。

早期 [before-aborted.txt](before-aborted.txt) 和 [before-aborted-resized.txt](before-aborted-resized.txt) 是缩减样本数前主动中断的探索，没有完整结果，不计入最终性能对比。

## 正式结果

镜像构建结束后开始正式采样；此窗口暂停其他安排中的构建、功能测试和 H1 压测，保留已有后台服务。before 完成后才应用新索引。以下单位均为毫秒，括号为全部实测样本范围；before 仅 3 次、after 15 次，不能据此估计生产容量或长期 P95。

| 场景 | 原查询中位数（范围） | 最终查询中位数（范围） | 中位数改善 |
| --- | --- | --- | --- |
| 英文非相邻多词 `binary invariant` | 6199.3 (6078.5–6809.7) | 329.2 (295.9–1077.8) | 18.8× |
| 三字中文 `不变式` | 6266.9 (5905.5–7661.6) | 310.2 (267.9–426.2) | 20.2× |
| 两字中文 `变式` | 7693.9 (6466.1–7718.8) | 1250.4 (806.2–2299.1) | 6.2× |
| 一字中文 `缀` | 7149.5 (6646.5–8740.3) | 1057.9 (735.0–3291.3) | 6.8× |

[before 原始输出](before.txt)、[before 数据及完整计划](before-results.json)、[final 原始输出](final.txt)、[final 数据及完整计划](final-results.json)、[对比 JSON](comparison.json)。final JSON 中的 `observed_p95_ms` 使用 nearest-rank；15 个样本时它等于本轮最大值，只是观测值。四种查询的 `same_as_before_and_actual_search` 均为 true：chunk ID、次序和浮点分数与旧查询及实际 `search()` 一致。

执行计划显示旧查询从 1,000 份作用域文档经外键索引读取约 5,000 个 chunk，在 OR 过滤时反复计算全文向量；**并非扫描全部 100,000 个 chunk**。最终方案的全文分支实际使用 `rag_chunk_content_fts_gin`，三字中文子串分支实际使用 `rag_chunk_content_trgm_gin`。1/2 字分支继续通过文档作用域和 chunk 外键索引扫描约 5,000 个 chunk，再对真正命中的候选排序，因此仍有约 1 秒中位数及最高 3.29 秒的观测尾延迟。没有丢掉短词召回，也没有限制候选数量。

[索引后三方案探索输出](indexed.txt) 和 [已完成场景 JSON](indexed-results.json) 表明只建索引、保留 OR 仍有额外重算：英文/三字中文单次样本分别约 1,271/1,748 ms，两字中文约 8,920 ms。全局 UNION 的两字查询在预热时触发 30 秒上限，探索到此停止，一字全局方案未再运行；这项未采用方案的失败没有记成通过。最终仅对生产采用的 scoped UNION 完成四类 15 样本与等价校验。各已完成查询均保存对应 `.sql` 和 `-plan.json`；超时查询没有伪造执行完成计划。

[迁移原始输出](migrate-indexes.txt) 记录两索引实际建立成功，总耗时 342.44 秒。新增 FTS GIN 为 5,267,456 bytes，trigram GIN 为 25,968,640 bytes，合计约 29.8 MiB；[storage.json](storage.json) 同时保留 chunk 堆及原有索引体积。这是本轮合成语料的实测体积，真实词汇分布、文本长度和写入率会改变成本。


## 保留的成本及部署要求

中文 1/2 字及没有可提取 trigram 的查询保留子串回退，仍可能扫描受权限约束的 chunk；不会以截断候选或丢掉短词召回来掩盖成本。大量匹配还需计算原始 FTS 分数并排序。GIN 索引只能加速其可用的匹配分支，不能保证所有查询都使用它。

迁移需可用的 PostgreSQL `pg_trgm` 扩展及创建扩展权限，或预先由数据库管理员安装；现有大语料建立索引时需写入维护窗口和额外磁盘空间。新索引由 Django 模型和迁移共同维护，无第三方分词库或新服务。检索签名、返回结构及 `postgres-fts-lexical-v1` 保持不变。
