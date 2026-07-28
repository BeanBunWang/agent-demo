from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from smolagents import tool

READ_EXTENSIONS = {".md", ".txt", ".json", ".csv"}
WRITE_EXTENSIONS = {".md", ".txt", ".json"}
INTENTS = {
    "inspect_files",
    "summarize_text",
    "analyze_csv",
    "system_check",
    "mixed",
    "unsupported",
}
MAX_READ_BYTES = 64 * 1024
MAX_WRITE_BYTES = 128 * 1024


class Trace:
    def __init__(self, emit: bool = True) -> None:
        self.events: list[dict[str, Any]] = []
        self.emit = emit

    def record(self, event: str, **data: Any) -> None:
        item = {"seq": len(self.events) + 1, "event": event, **data}
        self.events.append(item)
        if self.emit:
            print(json.dumps(item, ensure_ascii=False, default=str), flush=True)


class WorkspaceTools:
    def __init__(self, root: Path, trace: Trace) -> None:
        self.root = root.resolve()
        self.trace = trace
        self.read_roots = tuple((self.root / name).resolve() for name in ("examples", "workspace"))
        self.output_root = (self.root / "workspace" / "output").resolve()

    @staticmethod
    def _json(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _redact_content(data: dict[str, Any]) -> dict[str, Any]:
        redacted = dict(data)
        if "content" in redacted:
            redacted["content"] = f"<{len(str(redacted['content']))} chars>"
        return redacted

    def _relative(self, target: Path) -> str:
        return target.relative_to(self.root).as_posix()

    def _resolve_read(self, path: str) -> Path:
        relative = Path(path)
        if relative.is_absolute():
            raise ValueError("path_outside_workspace")
        target = (self.root / relative).resolve()
        if not any(target == base or base in target.parents for base in self.read_roots):
            raise ValueError("path_outside_workspace")
        return target

    def _resolve_output(self, path: str) -> Path:
        relative = Path(path)
        if relative.is_absolute():
            raise ValueError("path_outside_workspace")
        if relative.parts[:2] != ("workspace", "output"):
            relative = Path("workspace/output") / relative
        target = (self.root / relative).resolve()
        if self.output_root != target and self.output_root not in target.parents:
            raise ValueError("path_outside_workspace")
        return target

    def _run(
        self,
        name: str,
        arguments: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> str:
        self.trace.record("tool.called", tool=name, arguments=self._redact_content(arguments))
        try:
            result = operation()
        except ValueError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception as exc:  # 让 Agent 能观察并处理工具失败
            result = {"ok": False, "error": "tool_error", "detail": str(exc)}
        self.trace.record("tool.result", tool=name, result=self._redact_content(result))
        return self._json(result)

    def declare_intent(self, intent: str, plan: str) -> str:
        def operation() -> dict[str, Any]:
            if intent not in INTENTS:
                raise ValueError("invalid_intent")
            if any(event["event"] == "intent.declared" for event in self.trace.events):
                raise ValueError("intent_already_declared")
            if not plan.strip():
                raise ValueError("empty_plan")
            self.trace.record("intent.declared", intent=intent, plan=plan.strip())
            return {"ok": True, "intent": intent, "plan": plan.strip()}

        return self._run("declare_intent", {"intent": intent, "plan": plan}, operation)

    def list_workspace(self, path: str = ".") -> str:
        def operation() -> dict[str, Any]:
            if path == ".":
                bases = self.read_roots
            else:
                target = self._resolve_read(path)
                if not target.exists():
                    raise ValueError("path_not_found")
                if not target.is_dir():
                    raise ValueError("not_a_directory")
                bases = (target,)
            files: list[str] = []
            for base in bases:
                if not base.exists():
                    continue
                files.extend(
                    item.relative_to(self.root).as_posix()
                    for item in base.rglob("*")
                    if item.is_file() and not item.is_symlink()
                )
            return {"ok": True, "path": path, "files": sorted(files)[:100]}

        return self._run("list_workspace", {"path": path}, operation)

    def read_text(self, path: str) -> str:
        def operation() -> dict[str, Any]:
            target = self._resolve_read(path)
            if not target.exists():
                raise ValueError("path_not_found")
            if not target.is_file() or target.is_symlink():
                raise ValueError("not_a_regular_file")
            if target.suffix.lower() not in READ_EXTENSIONS:
                raise ValueError("unsupported_extension")
            if target.stat().st_size > MAX_READ_BYTES:
                raise ValueError("file_too_large")
            content = target.read_text(encoding="utf-8-sig")
            return {
                "ok": True,
                "path": self._relative(target),
                "bytes": target.stat().st_size,
                "content": content,
            }

        return self._run("read_text", {"path": path}, operation)

    @staticmethod
    def _number(value: float) -> int | float:
        return int(value) if value.is_integer() else round(value, 6)

    def _numeric_summary(self, values: list[float]) -> dict[str, int | float]:
        total = sum(values)
        return {
            "sum": self._number(total),
            "min": self._number(min(values)),
            "max": self._number(max(values)),
            "avg": self._number(total / len(values)),
        }

    def analyze_csv(self, path: str) -> str:
        def operation() -> dict[str, Any]:
            target = self._resolve_read(path)
            if not target.exists():
                raise ValueError("path_not_found")
            if target.suffix.lower() != ".csv":
                raise ValueError("unsupported_extension")
            if target.stat().st_size > MAX_READ_BYTES:
                raise ValueError("file_too_large")
            with target.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                columns = reader.fieldnames or []
            numeric: dict[str, list[float]] = {}
            for column in columns:
                try:
                    values = [float(row[column]) for row in rows if row[column] != ""]
                except (TypeError, ValueError):
                    continue
                if len(values) == len(rows) and values:
                    numeric[column] = values
            summary = {
                column: self._numeric_summary(values)
                for column, values in numeric.items()
            }
            group_column = next((column for column in columns if column not in numeric), None)
            groups: dict[str, dict[str, int | float]] = {}
            if group_column:
                for row in rows:
                    key = row[group_column]
                    bucket = groups.setdefault(key, {column: 0 for column in numeric})
                    for column in numeric:
                        bucket[column] = self._number(float(bucket[column]) + float(row[column]))
            result: dict[str, Any] = {
                "ok": True,
                "path": self._relative(target),
                "row_count": len(rows),
                "columns": columns,
                "numeric_summary": summary,
                "group_by": {"column": group_column, "groups": groups} if group_column else None,
            }
            if groups and "revenue" in numeric:
                winner, values = max(groups.items(), key=lambda item: float(item[1]["revenue"]))
                result["top_group_by_revenue"] = {"group": winner, "value": values["revenue"]}
            return result

        return self._run("analyze_csv", {"path": path}, operation)

    def write_output(self, path: str, content: str) -> str:
        def operation() -> dict[str, Any]:
            target = self._resolve_output(path)
            if target.suffix.lower() not in WRITE_EXTENSIONS:
                raise ValueError("unsupported_extension")
            encoded = content.encode("utf-8")
            if len(encoded) > MAX_WRITE_BYTES:
                raise ValueError("content_too_large")
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=target.parent,
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(content)
                    temp_path = Path(handle.name)
                os.replace(temp_path, target)
            finally:
                if temp_path and temp_path.exists():
                    temp_path.unlink()
            return {
                "ok": True,
                "path": self._relative(target),
                "bytes": len(encoded),
            }

        return self._run("write_output", {"path": path, "content": content}, operation)

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def run_local_check(self, check: str) -> str:
        def operation() -> dict[str, Any]:
            if check == "working_directory":
                return {"ok": True, "check": check, "value": str(self.root)}
            if check == "python_version":
                completed = self._run_command([sys.executable, "--version"])
                return {
                    "ok": completed.returncode == 0,
                    "check": check,
                    "value": (completed.stdout or completed.stderr).strip(),
                }
            if check == "git_status":
                probe = self._run_command(["git", "rev-parse", "--is-inside-work-tree"])
                if probe.returncode != 0:
                    return {"ok": True, "check": check, "available": False, "value": ""}
                status = self._run_command(["git", "status", "--short", "--branch"])
                return {
                    "ok": status.returncode == 0,
                    "check": check,
                    "available": True,
                    "value": status.stdout.strip(),
                }
            raise ValueError("unsupported_local_check")

        return self._run("run_local_check", {"check": check}, operation)

    def as_agent_tools(self) -> list[Any]:
        controller = self

        @tool
        def declare_intent(intent: str, plan: str) -> str:
            """在执行其他动作前，声明请求意图和有序工具计划。

            Args:
                intent: 工作区技能支持的意图名称。
                plan: 简短的有序计划，写明要调用的工具。
            """
            return controller.declare_intent(intent, plan)

        @tool
        def list_workspace(path: str = ".") -> str:
            """列出 examples 或 workspace 允许目录下的文件。

            Args:
                path: 相对目录路径；传入点号表示全部允许目录。
            """
            return controller.list_workspace(path)

        @tool
        def read_text(path: str) -> str:
            """读取允许范围内的小型文本、Markdown、JSON 或 CSV 文件。

            Args:
                path: examples 或 workspace 下的相对路径。
            """
            return controller.read_text(path)

        @tool
        def analyze_csv(path: str) -> str:
            """为允许范围内的 CSV 文件计算确定性统计结果。

            Args:
                path: examples 或 workspace 下的 CSV 相对路径。
            """
            return controller.analyze_csv(path)

        @tool
        def write_output(path: str, content: str) -> str:
            """仅在 workspace/output 下以原子方式写入文本。

            Args:
                path: 以 md、txt 或 json 结尾的相对输出路径。
                content: 要写入的完整文本内容。
            """
            return controller.write_output(path, content)

        @tool
        def run_local_check(check: str) -> str:
            """执行一项固定的本机检查，不接受命令行参数。

            Args:
                check: python_version、working_directory 或 git_status 之一。
            """
            return controller.run_local_check(check)

        return [
            declare_intent,
            list_workspace,
            read_text,
            analyze_csv,
            write_output,
            run_local_check,
        ]
