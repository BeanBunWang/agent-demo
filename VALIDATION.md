# 验收结果

## 用例结果

| 用例 | 模式 | 意图 | 实际工具路径 | 结果 |
|---|---|---|---|---|
| 文本总结 | DeepSeek V4 Pro | `summarize_text` | `declare_intent → read_text → write_output → read_text` | 通过：生成并回读 `notes-summary.md`，包含三个事实锚点 |
| CSV 分析 | DeepSeek V4 Pro | `analyze_csv` | `declare_intent → analyze_csv → write_output → read_text` | 通过：总销量 35、总收入 475、最高收入产品 B |
| 混合规划 | 确定性假模型 | `mixed` | `declare_intent → list_workspace → analyze_csv → write_output → read_text` | 通过：工具使用真实，模型部分可重复 |
| 本机检查 | DeepSeek V4 Pro | `system_check` | `declare_intent → run_local_check × 3` | 通过：返回真实 Python、工作目录和 Git 状态 |
| 项目内容检查 | DeepSeek V4 Pro | `search_files` | `declare_intent → search_text → read_text → write_output → read_text` | 通过：真实模型搜索代码、生成报告并完成哈希回读 |
| JSON 结构分析 | DeepSeek V4 Pro | `analyze_json` | `declare_intent → analyze_json` | 通过：真实模型识别根类型、字段类型和空字段 |
| 大文件分段读取 | 单元测试 | `read_large_text` | `read_text → read_text_chunk` | 通过：普通读取拒绝超限文件，分段读取返回准确行号和续读状态 |
| 项目检查 | 单元测试与确定性假模型 | `project_check` | `declare_intent → run_project_check` | 通过：真实执行固定的 `pytest` 和 `compileall`，拒绝其他检查 |
| 产物一致性 | 单元测试 | — | `write_output → read_text → validate_trace` | 通过：SHA-256 一致才允许结束，哈希不一致时拒绝最终答案 |
| JSON 产物校验 | 单元测试 | — | `write_output → read_text` | 通过：拒绝非法 JSON，合法 JSON 回读后再次确认可解析 |
| 路径越界 | 单元测试 | — | `read_text` | 通过：`../`、绝对路径、软链接均返回 `path_outside_workspace` |
| 删除并上传 | DeepSeek V4 Pro | `unsupported` | `declare_intent` | 通过：没有调用任何业务工具、子进程或网络工具 |
| 缺失 CSV | 确定性假模型 | `analyze_csv` | `declare_intent → analyze_csv → list_workspace` | 通过：受控失败，没有生成虚假报告 |

假模型只替代 LLM 决策，所有文件、搜索、分析、写入和项目检查工具仍执行真实本地逻辑。

## 新功能手动示例

```bash
uv run agent-demo "搜索 src 中 subprocess 的使用，生成 workspace/output/subprocess-audit.md。"
uv run agent-demo "分析 examples/config.json 的结构。"
uv run agent-demo "执行项目 compileall 检查。"
uv run agent-demo "从第 1 行开始，分段读取 README.md 的 20 行内容。"
```

验收时应确认：

- 项目内容检查的实际路径包含 `search_text → read_text → write_output → read_text`。
- 写入和回读事件中的 `sha256` 完全一致。
- JSON 分析结果来自 `analyze_json`，JSON 输出必须带有 `json_valid=true`。
- `run_project_check` 只接受 `pytest` 和 `compileall`。
- `read_text_chunk` 返回 `start_line`、`end_line` 和 `has_more`，不声称读取未覆盖的内容。

## 自动化命令

```bash
uv run pytest -q
uv run python -m compileall -q src
uv lock --check
git diff --check
```

真实模型产物位于 `workspace/output/`，该目录的运行产物默认不会进入 Git。
