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
uv run agent-demo "搜索 src 中 subprocess 的使用，生成 workspace/output/subprocess-audit.md。"
uv run agent-demo "分析 examples/config.json 的结构。"
uv run agent-demo "执行项目 compileall 检查。"
uv run agent-demo "告诉我本机 Python 版本、当前工作目录和 Git 状态。"
```

运行时以 JSONL 输出意图、工具调用、结果和验证状态。

## 工具与能力边界

- 文件工具：目录查看、小文件读取、2MB 内分段读取、文本搜索和原子写入
- 数据工具：CSV 确定性统计、JSON 结构分析
- 项目工具：固定执行 `pytest` 或 `compileall`，不接受额外命令行参数
- 可读目录：`examples/`、`workspace/`、`src/`、`tests/`、`skills/`
- 可读项目文件：`README.md`、`VALIDATION.md`、`pyproject.toml`、`.env.example`
- 可读类型：`.md/.txt/.json/.csv/.py/.toml/.yaml/.yml/.example`
- 可写：仅 `workspace/output/` 下的 `.md/.txt/.json`
- 本机检查：仅 Python 版本、当前目录和 Git 状态
- 不支持：任意命令行/Python、网络工具、删除、路径越界、修改项目源码

写入后必须回读；Runtime 会核对 SHA-256，JSON 输出还必须通过真实解析。

## 验证

```bash
uv run pytest -q
uv run python -m compileall -q src
uv lock --check
git diff --check
```
