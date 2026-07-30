import json
import re
from pathlib import Path

from agent_demo.tools import MAX_READ_BYTES, Trace, WorkspaceTools


def result(value: str) -> dict:
    return json.loads(value)


def test_file_and_csv_tools_close_the_loop(demo_root: Path) -> None:
    tools = WorkspaceTools(demo_root, Trace(emit=False))

    listed = result(tools.list_workspace("examples"))
    assert listed["files"] == [
        "examples/config.json",
        "examples/notes.md",
        "examples/sales.csv",
    ]

    notes = result(tools.read_text("examples/notes.md"))
    assert notes["ok"] and "smolagents" in notes["content"]
    assert len(notes["sha256"]) == 64

    stats = result(tools.analyze_csv("examples/sales.csv"))
    assert stats["row_count"] == 3
    assert stats["numeric_summary"]["units"]["sum"] == 35
    assert stats["numeric_summary"]["revenue"]["sum"] == 475
    assert stats["top_group_by_revenue"] == {"group": "B", "value": 300}

    written = result(tools.write_output("report.md", "# 已验证"))
    assert written["path"] == "workspace/output/report.md"
    read_back = result(tools.read_text(written["path"]))
    assert read_back["content"] == "# 已验证"
    assert read_back["sha256"] == written["sha256"]


def test_path_extension_and_size_guards(demo_root: Path) -> None:
    tools = WorkspaceTools(demo_root, Trace(emit=False))
    assert result(tools.read_text("../../.ssh/config"))["error"] == "path_outside_workspace"
    assert result(tools.read_text("/etc/passwd"))["error"] == "path_outside_workspace"
    assert result(tools.write_output("../escape.md", "拒绝"))["error"] == "path_outside_workspace"
    assert result(tools.write_output("bad.py", "拒绝"))["error"] == "unsupported_extension"

    large = demo_root / "examples/large.txt"
    large.write_bytes(b"x" * (MAX_READ_BYTES + 1))
    assert result(tools.read_text("examples/large.txt"))["error"] == "file_too_large"

    (demo_root / ".env").write_text("SECRET=不得读取", encoding="utf-8")
    (demo_root / ".env.example").write_text("SECRET=", encoding="utf-8")
    assert result(tools.read_text(".env"))["error"] == "path_outside_workspace"
    assert result(tools.read_text(".env.example"))["ok"] is True
    assert result(tools.search_text("不得读取"))["count"] == 0


def test_symlink_escape_is_blocked(demo_root: Path, tmp_path: Path) -> None:
    secret = tmp_path.parent / "outside-secret.txt"
    secret.write_text("不得泄露", encoding="utf-8")
    (demo_root / "examples/link.txt").symlink_to(secret)
    tools = WorkspaceTools(demo_root, Trace(emit=False))
    assert result(tools.read_text("examples/link.txt"))["error"] == "path_outside_workspace"


def test_intent_and_local_check_allowlist(demo_root: Path) -> None:
    trace = Trace(emit=False)
    tools = WorkspaceTools(demo_root, trace)
    assert result(tools.declare_intent("system_check", "检查 Python"))["ok"]
    assert result(tools.declare_intent("system_check", "再次声明"))["error"] == "intent_already_declared"
    assert re.match(r"Python \d+\.\d+", result(tools.run_local_check("python_version"))["value"])
    assert result(tools.run_local_check("working_directory"))["value"] == str(demo_root)
    assert result(tools.run_local_check("git_status"))["available"] is False
    assert result(tools.run_local_check("curl"))["error"] == "unsupported_local_check"


def test_search_chunk_json_and_project_check_tools(demo_root: Path) -> None:
    tools = WorkspaceTools(demo_root, Trace(emit=False))

    searched = result(tools.search_text("subprocess", "src"))
    assert searched["count"] == 2
    assert searched["matches"][0]["path"] == "src/demo.py"

    large = demo_root / "examples/large.txt"
    large.write_text("".join(f"{index:04d} " + "x" * 80 + "\n" for index in range(1000)))
    assert result(tools.read_text("examples/large.txt"))["error"] == "file_too_large"
    chunk = result(tools.read_text_chunk("examples/large.txt", 501, 3))
    assert chunk["start_line"] == 501
    assert chunk["end_line"] == 503
    assert chunk["has_more"] is True
    assert chunk["content"].startswith("0500 ")

    analyzed = result(tools.analyze_json("examples/config.json"))
    assert analyzed["root_type"] == "object"
    assert analyzed["field_types"] == {
        "service": "string",
        "enabled": "boolean",
        "owner": "null",
    }
    assert analyzed["null_fields"] == ["owner"]

    assert result(tools.run_project_check("compileall"))["ok"] is True
    assert result(tools.run_project_check("pytest"))["ok"] is True


def test_new_tool_guards_and_json_output_validation(demo_root: Path) -> None:
    tools = WorkspaceTools(demo_root, Trace(emit=False))

    assert result(tools.search_text("", "."))["error"] == "empty_query"
    assert result(tools.search_text("x", ".", 0))["error"] == "invalid_max_results"
    assert result(tools.read_text_chunk("examples/notes.md", 0, 10))["error"] == "invalid_start_line"
    assert result(tools.read_text_chunk("examples/notes.md", 99, 10))["error"] == "line_out_of_range"
    assert result(tools.analyze_json("examples/notes.md"))["error"] == "unsupported_extension"
    assert result(tools.run_project_check("ruff"))["error"] == "unsupported_project_check"

    (demo_root / "examples/bad.json").write_text("{bad", encoding="utf-8")
    assert result(tools.analyze_json("examples/bad.json"))["error"] == "invalid_json"
    assert result(tools.write_output("bad.json", "{bad"))["error"] == "invalid_json_content"

    written = result(tools.write_output("good.json", '{"ok": true}'))
    read_back = result(tools.read_text(written["path"]))
    assert read_back["json_valid"] is True
    assert read_back["sha256"] == written["sha256"]
