from pathlib import Path

import pytest


@pytest.fixture
def demo_root(tmp_path: Path) -> Path:
    (tmp_path / "examples").mkdir()
    (tmp_path / "workspace/output").mkdir(parents=True)
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills/workspace.md").write_text(
        "先声明意图，再使用工具；每次写入后都要回读输出。",
        encoding="utf-8",
    )
    (tmp_path / "examples/notes.md").write_text(
        "smolagents runtime\n白名单工具\n回读验证\n",
        encoding="utf-8",
    )
    (tmp_path / "examples/sales.csv").write_text(
        "product,units,revenue\nA,10,100\nB,20,300\nA,5,75\n",
        encoding="utf-8",
    )
    return tmp_path
