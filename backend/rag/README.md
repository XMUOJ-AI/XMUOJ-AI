# RAG 资料入库与检索

默认 `RAG_RETRIEVAL_BACKEND=postgres` 使用实际 PostgreSQL 全文检索和中文子串匹配，返回 `postgres-fts-lexical-v1`。它不产生或伪装向量相似度。资料只由本地管理命令入库；学生端通过 Agent 的受控检索工具读取。

PostgreSQL 迁移 `rag.0002_lexical_search_indexes` 为 `to_tsvector('simple', COALESCE(content, ''))` 和 `UPPER(content)` 建立匹配查询表达式的 GIN 索引。后者使用 PostgreSQL 自带 `pg_trgm` 扩展；迁移账号须具备在该数据库创建此扩展的权限，或由数据库管理员预先安装。项目启用标准 `django.contrib.postgres` AppConfig，以正确生成 Django 3.2 的 OpClass 表达式索引。索引建立会锁住写入；已有大语料的部署需安排维护窗口，并预留索引空间。

查询分别取得全文匹配和字面子串匹配的候选 ID，用 `UNION` 去重，再统一按原 `ts_rank` 降序、chunk UUID 升序取前五条；标题相同不会合并资料。英文多词仍使用 `plainto_tsquery(simple)` 的全部词匹配，子串分支仍忽略大小写并将 `%`、`_`、反斜线视作字面字符。两条分支及最终结果均保留当前资料范围、状态、知识点和题目可见性过滤；检索 API 和版本标识不变。

1/2 字中文或没有可提取 trigram 的符号查询仍保留任意子串召回，通常需要扫描当前知识点/题目范围内的候选资料；高频词的大量命中也需要排序。索引不能消除这些成本，不能据此声称任意短词都有固定低延迟。原理见 [PostgreSQL 14 pg_trgm 索引说明](https://www.postgresql.org/docs/14/pgtrgm.html#id-1.11.7.42.7)。本轮真实查询计划、语料说明和复现脚本位于 [H5 RAG 证据目录](../../docs/reviews/backend-h1-h7-evidence-2026-10-07/h5/rag/)。

入库必须指定未禁用的 Super Admin。默认资料为 `pending`，人工审核后可在输入 JSON 中明确设置 `active`。同来源、同清洗正文的重复导入复用同一文档；相同输入不会清空索引。权限、状态或元数据变更会清空本地索引标记，随后重建。新版本为 pending 时旧 active 版本继续可用，新版本启用后旧版本标为 disabled。

JSON 字段是 `title`、`source_type`、`source_id`、`source_url`（可省略）、`content`、`access_scope`、`status`、`metadata`。`metadata.knowledge_id` 使用知识点内部整数 ID；`metadata.problem_id` 使用题目展示编号。题目和题解资料必须带题目绑定。学生范围只接受可见普通题和 active 知识点，题解、完整程序或明显凭据不能进入学生范围。导入不抓取来源 URL，也不读取提交或隐藏测试点。

在 backend 目录运行：

```sh
python manage.py ingest_rag /absolute/path/document.json --actor 1
python manage.py ingest_rag /absolute/path/document.json --actor 1 --index --create-collection
python manage.py rebuild_rag_index --document DOCUMENT_UUID --create-collection
```

可选 Milvus REST v2 模式需要配置：

| 配置 | 含义 |
| --- | --- |
| `RAG_RETRIEVAL_BACKEND=milvus` | 启用向量检索 |
| `RAG_EMBEDDING_URL` | 完整 OpenAI 格式 Embedding HTTP(S) endpoint |
| `RAG_EMBEDDING_MODEL` | 真实服务的模型名 |
| `RAG_EMBEDDING_API_KEY` | 服务凭据，可省略用于本地服务 |
| `RAG_EMBEDDING_VERSION` | 索引版本，默认 v1 |
| `RAG_MILVUS_URL` | Milvus 基础 HTTP(S) URL |
| `RAG_MILVUS_TOKEN` | Milvus Bearer 凭据 |
| `RAG_MILVUS_COLLECTION` | 集合名，默认 xmuoj_rag |

单个 HTTP 请求及其重试共用默认 15 秒预算，连接失败、429/502/503/504 在预算内最多重试一次，不跟随重定向。一次检索的 embedding 与向量搜索共用调用方给定的预算，默认共 30 秒。缺少服务、响应格式错误或索引失败返回明确的 `AGENT_DEPENDENCY_NOT_READY`，不会生成假向量或假结果。向量写入使用稳定 chunk UUID，可安全重跑失败文档；成功写入后才记录 embedding 模型与版本，重建期间资料变更会阻止写入过期标记。改变向量维数时应配置新集合并重建。

检索同时限制 collection、embedding 模型/版本、知识点/题目和学生范围；每条返回结果再经过 PostgreSQL 当前状态、权限、题目可见性和 content_hash 检查。资料禁用或题目隐藏即时停止返回，即使外部向量尚未清理。运行重建命令可清除 disabled 资料的向量。

`python manage.py test rag --settings=oj.settings` 覆盖真实 PostgreSQL 查询和本地 HTTP 协议夹具。HTTP 夹具验证超时、重试、索引恢复、幂等和恶意响应；它不代表已连接部署环境中的 Embedding/Milvus 服务。Milvus 请求结构按 [REST v2 集合创建](https://milvus.io/api-reference/restful/v2.6.x/v2/Collection%20%28v2%29/Create.md) 与 [向量检索](https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20%28v2%29/Search.md) 定义实现。
