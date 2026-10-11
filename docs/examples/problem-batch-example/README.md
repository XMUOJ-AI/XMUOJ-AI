# JSONL 中间层构建输入

本目录是 `build_qduoj_batch.py` 的标准化 JSONL 输入 fixture，不是后端正式交付包。`build-config.json` 只给构建器提供可重现的批次和生产者信息，不是正式交付 `manifest.json`。

正式黄金交付包为上级目录的 `problem-batch-example.zip`，解压内容同旁边的 `qduoj-problem-batch-example/`。

重新构建：

```bash
python3 tools/problem_batch/build_qduoj_batch.py \
  docs/examples/problem-batch-example \
  docs/examples/problem-batch-example.zip \
  --expanded-dir docs/examples/qduoj-problem-batch-example \
  --replace-expanded \
  --generated-at 2026-08-09T10:00:00Z
```
