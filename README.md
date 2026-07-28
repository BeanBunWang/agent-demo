# smolagents 本地工作区 Agent 演示

一个最小但完整的 Agent 闭环：意图识别与规划 → smolagents ReAct 运行时 → 白名单本地工具 → 回读验证 → 最终回答。

## 安装

```bash
uv sync
cp .env.example .env
```

在 `.env` 中设置 `DEEPSEEK_API_KEY`。默认使用 `deepseek-v4-pro` 并开启思考模式。

## 运行

```bash
uv run agent-demo --show-tools
uv run agent-demo "读取 examples/notes.md，生成 workspace/output/notes-summary.md，用三点总结。"
uv run agent-demo "分析 examples/sales.csv，并生成 workspace/output/sales-report.md。"
uv run agent-demo "告诉我本机 Python 版本、当前工作目录和 Git 状态。"
```

运行时以 JSONL 输出意图、工具调用、结果和验证状态。

## 能力边界

- 可读：`examples/`、`workspace/` 下的 `.md/.txt/.json/.csv`
- 可写：仅 `workspace/output/` 下的 `.md/.txt/.json`
- 本机检查：仅 Python 版本、当前目录和 Git 状态
- 不支持：任意命令行/Python、网络工具、删除、路径越界、修改项目源码

## 验证

```bash
uv run pytest -q
uv run python -m compileall -q src
uv lock --check
git diff --check
```
