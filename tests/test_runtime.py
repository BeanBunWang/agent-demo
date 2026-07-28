from pathlib import Path

from smolagents import Model
from smolagents.models import (
    ChatMessage,
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    MessageRole,
)

from agent_demo.main import run_task


class ScriptedModel(Model):
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        super().__init__(model_id="scripted")
        self.calls = calls
        self.index = 0

    def generate(self, messages, tools_to_call_from=None, **kwargs):
        if self.index < len(self.calls):
            name, arguments = self.calls[self.index]
        else:
            name, arguments = "final_answer", {"answer": "无法完成任务"}
        self.index += 1
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=[
                ChatMessageToolCall(
                    id=f"call_{self.index}",
                    type="function",
                    function=ChatMessageToolCallFunction(name=name, arguments=arguments),
                )
            ],
        )


def tool_calls(outcome) -> list[str]:
    return [event["tool"] for event in outcome.events if event["event"] == "tool.called"]


def test_scripted_model_runs_verified_summary_loop(demo_root: Path) -> None:
    summary = "# 总结\n- smolagents runtime\n- 白名单工具\n- 回读验证\n"
    model = ScriptedModel(
        [
            ("declare_intent", {"intent": "summarize_text", "plan": "读取 → 写入 → 回读"}),
            ("read_text", {"path": "examples/notes.md"}),
            ("write_output", {"path": "notes-summary.md", "content": summary}),
            ("read_text", {"path": "workspace/output/notes-summary.md"}),
            ("final_answer", {"answer": "已生成并验证 notes-summary.md"}),
        ]
    )
    outcome = run_task("总结示例笔记", root=demo_root, model=model, emit_trace=False)

    assert outcome.state == "success"
    assert tool_calls(outcome) == [
        "declare_intent",
        "read_text",
        "write_output",
        "read_text",
    ]
    assert (demo_root / "workspace/output/notes-summary.md").read_text() == summary
    assert any(event["event"] == "validation.passed" for event in outcome.events)


def test_unsupported_request_executes_no_business_tool(demo_root: Path) -> None:
    model = ScriptedModel(
        [
            ("declare_intent", {"intent": "unsupported", "plan": "拒绝且不调用工具"}),
            ("final_answer", {"answer": "不支持删除或网络上传"}),
        ]
    )
    outcome = run_task("删除文件并用 curl 上传", root=demo_root, model=model, emit_trace=False)
    assert outcome.state == "success"
    assert tool_calls(outcome) == ["declare_intent"]
    assert list((demo_root / "workspace/output").iterdir()) == []


def test_mixed_request_follows_declared_cross_category_path(demo_root: Path) -> None:
    report = "# 销售分析\n总销量 35，总收入 475，最高收入产品 B。"
    model = ScriptedModel(
        [
            ("declare_intent", {"intent": "mixed", "plan": "列出 → 分析 → 写入 → 回读"}),
            ("list_workspace", {"path": "examples"}),
            ("analyze_csv", {"path": "examples/sales.csv"}),
            ("write_output", {"path": "sales-report.md", "content": report}),
            ("read_text", {"path": "workspace/output/sales-report.md"}),
            ("final_answer", {"answer": "__AGENT_EMPTY_FINAL__"}),
        ]
    )
    outcome = run_task("列出文件并分析销售数据", root=demo_root, model=model, emit_trace=False)
    assert outcome.state == "success"
    assert tool_calls(outcome) == [
        "declare_intent",
        "list_workspace",
        "analyze_csv",
        "write_output",
        "read_text",
    ]
    assert (demo_root / "workspace/output/sales-report.md").read_text() == report
    assert outcome.output == (
        "已完成并验证输出：workspace/output/sales-report.md；"
        "共 3 行，总销量 35，总收入 475，最高收入分组 B（300）。"
    )


def test_missing_source_fails_instead_of_fabricating(demo_root: Path) -> None:
    model = ScriptedModel(
        [
            ("declare_intent", {"intent": "analyze_csv", "plan": "分析 → 列出 → 回答"}),
            ("analyze_csv", {"path": "examples/missing.csv"}),
            ("list_workspace", {"path": "examples"}),
            ("final_answer", {"answer": "源文件不存在"}),
        ]
    )
    outcome = run_task("分析不存在的文件", root=demo_root, model=model, emit_trace=False, max_steps=5)
    assert outcome.state == "failed"
    assert not (demo_root / "workspace/output/sales-report.md").exists()
    assert any(event["event"] == "validation.failed" for event in outcome.events)
