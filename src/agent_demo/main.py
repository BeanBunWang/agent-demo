from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from smolagents import OpenAIModel, ToolCallingAgent
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction

from .tools import Trace, WorkspaceTools

REQUIRED_TOOLS = {
    "inspect_files": {"list_workspace"},
    "summarize_text": {"read_text", "write_output"},
    "analyze_csv": {"analyze_csv", "write_output"},
    "system_check": {"run_local_check"},
    "mixed": {"list_workspace", "analyze_csv", "write_output"},
}


@dataclass
class RunOutcome:
    output: str
    state: str
    events: list[dict[str, Any]]


class ChineseArgumentParser(argparse.ArgumentParser):
    """把 argparse 的固定帮助标题转换为中文。"""

    def format_help(self) -> str:
        return (
            super()
            .format_help()
            .replace("usage:", "用法：")
            .replace("positional arguments:", "位置参数：")
            .replace("options:", "选项：")
        )

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法：")

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: 错误：{message}\n")


class DeepSeekModel(OpenAIModel):
    """把普通最终回复适配为 smolagents 的 final_answer 工具调用。"""

    def generate(self, *args: Any, **kwargs: Any) -> ChatMessage:
        message = super().generate(*args, **kwargs)
        for _ in range(2):
            if message.tool_calls or message.content:
                break
            message = super().generate(*args, **kwargs)
        if message.tool_calls:
            return message
        content = message.content
        if not content:
            content = "__AGENT_EMPTY_FINAL__"
        return ChatMessage(
            role=message.role,
            content=None,
            tool_calls=[
                ChatMessageToolCall(
                    id="deepseek_final_answer",
                    type="function",
                    function=ChatMessageToolCallFunction(
                        name="final_answer",
                        arguments={"answer": str(content)},
                    ),
                )
            ],
            raw=message.raw,
            token_usage=message.token_usage,
        )


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _successful_results(events: list[dict[str, Any]], tool: str) -> list[tuple[int, dict[str, Any]]]:
    return [
        (index, event["result"])
        for index, event in enumerate(events)
        if event["event"] == "tool.result"
        and event.get("tool") == tool
        and event["result"].get("ok") is True
    ]


def validate_trace(trace: Trace) -> tuple[bool, str]:
    declarations = [event for event in trace.events if event["event"] == "intent.declared"]
    calls = [event["tool"] for event in trace.events if event["event"] == "tool.called"]
    if not declarations or not calls or calls[0] != "declare_intent":
        return False, "intent_must_be_declared_first"
    intent = declarations[0]["intent"]
    business_calls = [name for name in calls if name != "declare_intent"]
    if intent == "unsupported":
        return (not business_calls, "unsupported_request_must_not_execute_tools")

    required = REQUIRED_TOOLS[intent]
    successful = {
        event["tool"]
        for event in trace.events
        if event["event"] == "tool.result" and event["result"].get("ok") is True
    }
    if not required.issubset(successful):
        return False, f"missing_successful_tools:{','.join(sorted(required - successful))}"

    writes = _successful_results(trace.events, "write_output")
    reads = _successful_results(trace.events, "read_text")
    for write_index, write in writes:
        if not any(index > write_index and read.get("path") == write.get("path") for index, read in reads):
            return False, f"output_not_read_back:{write.get('path')}"
    return True, "closed_loop_verified"


def _fallback_summary(trace: Trace) -> str:
    successful = [
        event
        for event in trace.events
        if event["event"] == "tool.result" and event["result"].get("ok") is True
    ]
    written = next(
        (event["result"] for event in reversed(successful) if event["tool"] == "write_output"),
        None,
    )
    analysis = next(
        (event["result"] for event in successful if event["tool"] == "analyze_csv"),
        None,
    )
    checks = [event["result"] for event in successful if event["tool"] == "run_local_check"]
    if written:
        text = f"已完成并验证输出：{written['path']}"
        if analysis:
            totals = analysis["numeric_summary"]
            top = analysis.get("top_group_by_revenue")
            text += f"；共 {analysis['row_count']} 行"
            if "units" in totals and "revenue" in totals:
                text += f"，总销量 {totals['units']['sum']}，总收入 {totals['revenue']['sum']}"
            if top:
                text += f"，最高收入分组 {top['group']}（{top['value']}）"
        return text + "。"
    if checks:
        return "；".join(f"{item['check']}: {item.get('value', '')}" for item in checks)
    inspected = next(
        (event["result"] for event in reversed(successful) if event["tool"] in {"read_text", "list_workspace"}),
        None,
    )
    if inspected:
        return f"本地检查已完成：{inspected.get('path', inspected.get('files', []))}"
    return "请求超出已注册工具的能力边界，未执行任何业务工具。"


def build_model(root: Path) -> OpenAIModel:
    load_dotenv(root / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("缺少 DEEPSEEK_API_KEY，请在 .env 或环境变量中设置")
    timeout = float(os.getenv("AGENT_MODEL_TIMEOUT", "180"))
    return DeepSeekModel(
        model_id=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        api_base=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key=api_key,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}},
        tool_choice="auto",
        max_tokens=4096,
        client_kwargs={"timeout": timeout, "max_retries": 1},
    )


def run_task(
    task: str,
    *,
    root: Path | None = None,
    model: Any | None = None,
    emit_trace: bool = True,
    max_steps: int = 10,
) -> RunOutcome:
    root = (root or project_root()).resolve()
    skill_path = root / "skills" / "workspace.md"
    if not skill_path.exists():
        raise ValueError(f"找不到工作区技能文件：{skill_path}")

    trace = Trace(emit=emit_trace)
    trace.record("runtime.started", task=task, max_steps=max_steps)
    controller = WorkspaceTools(root, trace)
    validation_passed = False

    def final_answer_check(final_answer: Any, memory: Any, agent: Any) -> bool:
        nonlocal validation_passed
        valid, reason = validate_trace(trace)
        trace.record("validation.passed" if valid else "validation.failed", reason=reason)
        validation_passed = valid
        return valid

    agent = ToolCallingAgent(
        tools=controller.as_agent_tools(),
        model=model or build_model(root),
        instructions=skill_path.read_text(encoding="utf-8"),
        max_steps=max_steps,
        verbosity_level=0,
        final_answer_checks=[final_answer_check],
        return_full_result=True,
    )
    try:
        result = agent.run(task)
    except Exception as exc:
        trace.record("runtime.failed", reason="agent_error", detail=str(exc))
        return RunOutcome(output=str(exc), state="failed", events=trace.events)

    output = str(result.output or "")
    if result.state == "success" and validation_passed:
        if output == "__AGENT_EMPTY_FINAL__":
            output = _fallback_summary(trace)
        trace.record(
            "runtime.completed",
            state=result.state,
            token_usage=str(result.token_usage) if result.token_usage else None,
        )
        state = "success"
    else:
        trace.record("runtime.failed", reason=result.state or "validation_failed")
        state = "failed"
    return RunOutcome(output=output, state=state, events=trace.events)


def _show_tools(root: Path) -> None:
    tools = WorkspaceTools(root, Trace(emit=False)).as_agent_tools()
    for item in tools:
        print(f"{item.name}: {item.description.splitlines()[0]}")


def main() -> int:
    parser = ChineseArgumentParser(
        description="最小化 smolagents 本地工作区 Agent 演示",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")
    parser.add_argument("task", nargs="?", help="要执行的自然语言任务")
    parser.add_argument("--show-tools", action="store_true", help="显示已注册的工具白名单")
    args = parser.parse_args()
    root = project_root()

    if args.show_tools:
        _show_tools(root)
        return 0
    if not args.task:
        parser.error("除非使用 --show-tools，否则必须提供任务")
    try:
        outcome = run_task(args.task, root=root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(outcome.output)
    return 0 if outcome.state == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
