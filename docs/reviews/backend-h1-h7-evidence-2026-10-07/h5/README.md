# H5：公开分页与 PostgreSQL RAG 检索

本目录仅记录 H5 的实现和实际验证；不是 H1–H7 总验收，也不替代外部模型/Milvus 联调。知识工作契约保持未冻结的0.9.9，修订标识为 `2026-10-07-H5`，原 `docs/knowledge/review-v0.9.9` 未修改。

## 公开知识查询

新增两条面向所有已登录身份的只读分页接口：

- `/api/knowledge-points/{code}/related-problems`：当前approved映射中的visible普通题，输出仅display_id/title；先按范围过滤再计数，不暴露隐藏题、比赛题、待审候选。
- `/api/knowledge-points/{code}/dependencies`：正式active邻接；direction=prerequisites/dependents，默认prerequisites。

page默认1、page_size默认20且最多100；题目按展示编号/数据库id排序，邻接按对方code/依赖id排序。最后一页之后返回空items与真实total；offset分页不提供跨请求冻结快照，资料变更后应刷新。未知/重复/非法参数400，匿名401，非active知识点和不存在对象404。

旧公开详情默认保留三种数组及原字段集合；每类不超过100项时继续返回完整集合。任一集合超限时，数据库最多读取该类101项便返回409 `KNOWLEDGE_PAGINATION_REQUIRED`，details明确超限集合、分页URL和可用的详情URL。显式请求 `?include_collections=false` 可读取大节点详情：三个集合数组为空，prerequisite_count/dependent_count仍为完整计数。没有静默截断或将旧数组改成分页对象。管理摘要/分页权限未改变。

本仓库没有前端知识详情HTTP调用方；Agent直接使用ORM和既有rag.search函数，不依赖旧公开详情。扫描见 [consumer-scan.txt](consumer-scan.txt)。知识操作数从19变为21，四份working OpenAPI的合计操作数从34变为36。

实现文件：`backend/knowledge/queries.py`、`views.py`、`urls.py`、`tests.py`；工作契约与说明：`docs/openapi/knowledge-api-v1.yaml`、`docs/knowledge/implementation-notes-2026-10-07.md`。摘要查询仅选取需要的题目/邻接字段，不加载每条题面的完整内容。

## 知识验证

在专用 PostgreSQL `xmuoj_h5` / `test_xmuoj_h5`（15432）和Redis16379运行：

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 新增分页回归 | 3项通过，4.867s；100/101详情边界、明确错误与显式opt-out、103关联题跨页排序/过滤/总数、101依赖分页、参数/身份/状态及响应Schema | [pagination-tests.txt](pagination-tests.txt) |
| 知识完整回归 | 25项通过，55.959s，含原审核/并发/引用保护与新增分页 | [knowledge-tests.txt](knowledge-tests.txt) |
| flake8 | 退出码0，无输出 | [knowledge-lint.txt](knowledge-lint.txt) |
| working契约与样例 | `contract validation passed` | [contracts.txt](contracts.txt)、[knowledge-results.json](knowledge-results.json) |

初次新建测试库在RAG OpClass表达式索引迁移处失败，未进入分页业务断言，见 [pagination-before.txt](pagination-before.txt)；它不是“分页修复前失败”的业务证据。根任务补齐Django自带的 `django.contrib.postgres` AppConfig后，生成SQL修正为 `USING gin ((UPPER(content)) gin_trgm_ops)`，之后新迁移和上述回归均通过，见 [rag-index-sql-check.txt](rag-index-sql-check.txt)。

知识命令（从根目录执行）：

```sh
POSTGRES_DB=xmuoj_h5 POSTGRES_PORT=15432 REDIS_PORT=16379 .venv/bin/python backend/manage.py test knowledge --settings=oj.settings --noinput --keepdb
.venv/bin/python tools/problem_batch/validate_contracts.py
```

lint从backend目录运行 `../.venv/bin/flake8 knowledge --statistics`。

## RAG 验证边界

RAG保持 `search(query, knowledge_id, problem_id=None, timeout=None)` 和结果结构；公开API/Agent工具不新增签名。PostgreSQL全文表达式GIN与原生pg_trgm表达式GIN需和查询共同部署；中文任意子串（包括1/2字）语义保留，不能因不足三个字符而拒绝/省略。短子串可能仍需扫描符合权限的候选，不能承诺所有查询都使用trigram索引。

RAG新增4项回归后完整17项通过，20.998s；覆盖1/2/3字中文、英文多词、排序/去重、通配字符字面量与资料权限撤回。迁移漂移检查输出 `No changes detected`，flake8退出0。原始输出、SQL、执行计划与复现脚本见 [RAG证据说明](rag/README.md)。知识与RAG本轮定向回归合计42项；这不是全库验收结果。

在同一确定性合成语料（全局100,000段，每知识点范围5,000段）上，优化前3次与优化后15次暖缓存顺序采样的中位数如下；before样本不足以报告P95，after观测尾部也不能作为生产SLA。

| 检索词 | 优化前中位数 | 优化后中位数 |
| --- | ---: | ---: |
| 英文多词 | 6199.32ms | 329.21ms |
| 三字中文 | 6266.86ms | 310.21ms |
| 两字中文 | 7693.89ms | 1250.45ms |
| 一字中文 | 7149.54ms | 1057.94ms |

四场景均通过优化前/后与实际 `search()` 的chunk ID、顺序及分数完全一致断言，见 [before-results.json](rag/before-results.json)、[final-results.json](rag/final-results.json)。实际计划显示英文与三字中文可使用对应内容GIN索引；一/两字中文保留范围内子串扫描。未采用的无范围约束UNION在两字查询触发30s超时，完整失败记录仍保留，不能将其作为成功方案。

测试环境为本机PostgreSQL14.23、QEMU amd64、3 vCPU、约4.1GB内存，旧服务容器仍常驻；H1测量及镜像构建未与正式采样并行。两项新索引约31.2MB，迁移耗时342.44s，见 [storage.json](rag/storage.json)；大语料上线需要索引构建维护窗口和额外空间。原优化前计划是范围内5,000段逐条计算全文向量，不是全站100,000段全文扫描。真实外部embedding/Milvus、用户网络及并发负载未参与本次PostgreSQL优化验收。
