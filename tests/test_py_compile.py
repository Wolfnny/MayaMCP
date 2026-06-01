from __future__ import annotations

import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_source_files_compile() -> None:
    paths = [
        ROOT / "src" / "maya_mcp_server.py",
        *sorted((ROOT / "src" / "maya_mcp").rglob("*.py")),
        *sorted((ROOT / "src" / "mayatools").rglob("*.py")),
    ]
    for path in paths:
        py_compile.compile(str(path), doraise=True)
