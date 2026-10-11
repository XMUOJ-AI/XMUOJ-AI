# XMUOJ-AI 第一期批量数据获取与交付契约

- 状态：已冻结
- 版本：1.0.0
- 更新日期：2026-08-10
- 交付任务：确定批量获取和交付数据的形式

## 1. 文件定位

本文件是“确定批量获取/交付数据形式”任务的唯一权威入口，汇总数据生产、审核、打包、上传、校验、提交和报告流程。为保持命令行工具、单元测试和黄金 ZIP 可直接运行，程序与样例仍作为本文件的附件独立保存。

完整字段和异常规则以 [problem-import-contract-v1.md](./problem-import-contract-v1.md) 及对应 JSON Schema 为准；本文件冻结交付边界、操作流程和验收入口。

## 2. 冻结结论

第一期采用两层数据形式：

1. **数据生产与审核中间层：标准化 JSONL。**
   每行是一条符合 `problem-import-v1.schema.json` 的题目记录，同时保存来源、授权、标签、知识点候选、内容哈希、原始快照引用和测试数据状态。
2. **提交给后端的正式交付层：QDUOJ-compatible ZIP。**
   可导入题目使用现有 QDUOJ 数字目录结构，即 `{directory}/problem.json + {directory}/testcase/`；ZIP 根目录增加批次 `manifest.json`、标签映射和审计元数据。

JSONL 不直接调用现有 OJ 题目导入端点。若未来改为 JSONL 直接入库，必须升级主版本并重新审批。

## 3. 数据流

```text
题目来源
  → 采集与原始快照
  → 标准化 problems.jsonl
  → 授权、去重、标签和知识点审核
  → 确定性构建 QDUOJ ZIP
  → 后端 dry-run 校验
  → 管理员幂等 commit
  → XMUOJ Problem + 导入报告
```

## 4. 中间层输入

构建目录至少包含：

```text
source-directory/
├── problems.jsonl
├── tag_mapping.csv
├── build-config.json              # 可选，仅用于构建参数
├── raw/                           # 可选原始快照
└── testcases/
    └── {problem_key}/
        ├── manifest.json
        ├── *.in
        └── *.out
```

关键规则：

- `problems.jsonl` 使用 UTF-8，每个非空行是一个完整 JSON 对象。
- 批次内 `problem_key` 唯一，`source_platform + source_id` 唯一。
- 所有文件路径必须是安全相对路径，不允许绝对路径、`..` 或符号链接逃逸。
- `tag_mapping.csv` 使用固定表头，记录来源标签、统一标签和知识点映射。
- `ready` 题目必须提供测试数据 manifest；`statement_only` 和 `needs_review` 只进入元数据层。
- 测试数据必须声明 SHA-256；第一期要求 UTF-8 文本并统一换行符。
- 第一阶段构建器支持 ACM/OI，拒绝 SPJ。

## 5. 正式 ZIP 输出

```text
batch.zip
├── manifest.json
├── tag_mapping.csv
├── metadata/
│   ├── problems.jsonl
│   └── raw/{problem_key}.json
└── 1/
    ├── problem.json
    └── testcase/
        ├── 1.in
        └── 1.out
```

### 5.1 `manifest.json`

批次清单记录：

- 格式和 Schema 版本；
- `batch_id`、生成时间和生产者；
- 来源平台、记录总数和可导入题目数；
- 每道题的 `problem_key`、元数据行号、数字目录和交付状态；
- 除 `manifest.json` 自身外每个载荷文件的路径、媒体类型、大小和 SHA-256。

### 5.2 QDUOJ 题目目录

- 数字目录连续分配给 `ready` 题目。
- `problem.json` 与现有 `ImportProblemSerializer` 字段形状一致。
- `display_id` 从来源平台和来源题号确定性生成。
- ACM 测试点输出固定分值 100；OI 测试点分值总和必须等于 `total_score`。
- `statement_only` 和 `needs_review` 不生成数字题目目录。

### 5.3 可复现性和完整性

- JSON 字段、文件条目和来源平台列表稳定排序。
- ZIP 条目使用固定时间戳、权限和压缩设置。
- 相同输入和 `generated_at` 必须生成字节完全一致的 ZIP。
- 后端可依据 manifest 的大小及 SHA-256 检测丢失或篡改文件。

## 6. 后端接收形式

常规批次通过管理 API 处理：

1. `POST /api/admin/problem-import/batches` 上传 ZIP，返回 `202 + batch_id`。
2. 后台异步解压并执行格式、Schema、哈希、权限、重复和题目兼容性校验。
3. 管理员通过批次、题目和错误查询接口进行 dry-run 审核。
4. `POST /batches/{batch_id}/commit` 携带 `Idempotency-Key` 幂等提交。
5. 后端按题事务处理并生成符合导入报告 Schema 的结果。

超大批次使用受控 Django Management Command，但输入包、校验规则、幂等语义和报告格式必须与管理 API 一致。

## 7. 构建、验证和复现

### 7.1 构建题包

```bash
python3 tools/problem_batch/build_qduoj_batch.py \
  docs/examples/problem-batch-example \
  /tmp/problem-batch.zip \
  --batch-id example-batch \
  --generated-at 2026-08-09T10:00:00Z
```

可使用 `--expanded-dir` 同时输出展开快照。构建器实现位于 [build_qduoj_batch.py](../tools/problem_batch/build_qduoj_batch.py)。

### 7.2 单元测试

```bash
python3 -m unittest discover -s tools/problem_batch/tests -v
```

测试覆盖可复现 ZIP、manifest 文件哈希、QDUOJ 序列化器形状、仅题面记录、路径穿越和来源重复，见 [test_build_qduoj_batch.py](../tools/problem_batch/tests/test_build_qduoj_batch.py)。

### 7.3 全部契约验证

```bash
python3 -m venv /tmp/xmuoj-contract-venv
/tmp/xmuoj-contract-venv/bin/pip install -r tools/problem_batch/requirements-contract.txt
/tmp/xmuoj-contract-venv/bin/python tools/problem_batch/validate_contracts.py
```

验证器检查六个 JSON Schema 的正反例、三个 OpenAPI、黄金 ZIP 的文件集合、大小、哈希及展开快照，见 [validate_contracts.py](../tools/problem_batch/validate_contracts.py)。

## 8. 附件清单

| 附件 | 用途 |
|---|---|
| [problem-import-contract-v1.md](./problem-import-contract-v1.md) | 完整字段、规模、安全、事务和错误规则 |
| [problem-import-v1.schema.json](./schemas/problem-import-v1.schema.json) | 标准化 JSONL 记录 Schema |
| [problem-testcase-manifest-v1.schema.json](./schemas/problem-testcase-manifest-v1.schema.json) | 测试数据来源 Schema |
| [qduoj-problem-v1.schema.json](./schemas/qduoj-problem-v1.schema.json) | QDUOJ `problem.json` Schema |
| [problem-batch-manifest-v1.schema.json](./schemas/problem-batch-manifest-v1.schema.json) | 正式批次 manifest Schema |
| [problem-import-report-v1.schema.json](./schemas/problem-import-report-v1.schema.json) | 导入报告 Schema |
| [problem-import-api-v1.yaml](./openapi/problem-import-api-v1.yaml) | 后端管理 API |
| [build_qduoj_batch.py](../tools/problem_batch/build_qduoj_batch.py) | JSONL → QDUOJ ZIP 构建器 |
| [validate_contracts.py](../tools/problem_batch/validate_contracts.py) | Schema、OpenAPI 和黄金包验证器 |
| [problem-batch-example](./examples/problem-batch-example/README.md) | 标准化输入样例 |
| [problem-batch-example.zip](./examples/problem-batch-example.zip) | 可复现黄金交付包 |
| [qduoj-problem-batch-example](./examples/qduoj-problem-batch-example/manifest.json) | 黄金包展开快照 |

## 9. 验收标准

“确定批量获取/交付数据形式”任务满足以下条件即视为完成：

- 明确标准化 JSONL 是中间层，QDUOJ-compatible ZIP 是正式后端交付层。
- 输入、输出、题目目录、测试数据、标签映射、manifest 和报告均有机器 Schema。
- 相同输入可以确定性生成相同 ZIP，所有载荷文件的大小和 SHA-256 可验证。
- 路径穿越、重复来源、非法状态、错误分值和哈希不一致会被拒绝。
- 常规批次的异步上传、游标查询、幂等 commit 和超大批次处理边界已经定义。
- 黄金输入、黄金 ZIP、展开快照、构建器和验证测试齐全。

当前 1.0.0 版本满足上述文档与机器契约验收条件。冻结不代表后端上传、异步校验、commit API 或 Management Command 已经实现。
