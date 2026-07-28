# 验收结果

## 用例结果

| 用例 | 模式 | 意图 | 实际工具路径 | 结果 |
|---|---|---|---|---|
| 文本总结 | DeepSeek V4 Pro | `summarize_text` | `declare_intent → read_text → write_output → read_text` | 通过：生成并回读 `notes-summary.md`，包含三个事实锚点 |
| CSV 分析 | DeepSeek V4 Pro | `analyze_csv` | `declare_intent → analyze_csv → write_output → read_text` | 通过：总销量 35、总收入 475、最高收入产品 B |
| 混合规划 | 确定性假模型 | `mixed` | `declare_intent → list_workspace → analyze_csv → write_output → read_text` | 通过：工具使用真实，模型部分可重复 |
| 本机检查 | DeepSeek V4 Pro | `system_check` | `declare_intent → run_local_check × 3` | 通过：返回真实 Python、工作目录和 Git 状态 |
| 路径越界 | 单元测试 | — | `read_text` | 通过：`../`、绝对路径、软链接均返回 `path_outside_workspace` |
| 删除并上传 | DeepSeek V4 Pro | `unsupported` | `declare_intent` | 通过：没有调用任何业务工具、子进程或网络工具 |
| 缺失 CSV | 确定性假模型 | `analyze_csv` | `declare_intent → analyze_csv → list_workspace` | 通过：受控失败，没有生成虚假报告 |

假模型只替代 LLM 决策，`list_workspace`、`read_text`、`analyze_csv`、`write_output` 和 `run_local_check` 仍执行真实本地逻辑。

## 自动化命令

```bash
uv run pytest -q
uv run python -m compileall -q src
uv lock --check
git diff --check
```

真实模型产物位于 `workspace/output/`，该目录的运行产物默认不会进入 Git。
