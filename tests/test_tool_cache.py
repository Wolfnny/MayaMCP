from __future__ import annotations

import base64
from pathlib import Path

from maya_mcp.server import MayaConnection, build_cached_tool_call_script, tool_source_hash


TOOL_SOURCE = '''from typing import Any, Dict


def sample_tool(value: int = 1) -> Dict[str, Any]:
    """Return the provided value."""
    return {"success": True, "value": value}
'''


def test_cached_tool_script_registers_source_as_base64() -> None:
    source_hash = tool_source_hash(TOOL_SOURCE)
    script = build_cached_tool_call_script(
        "sample_tool",
        TOOL_SOURCE,
        source_hash,
        {"value": 7},
        include_source=True,
    )

    encoded_source = base64.b64encode(TOOL_SOURCE.encode("utf-8")).decode("ascii")
    assert encoded_source in script
    assert "sample_tool" in script
    assert "MayaMCP tool cache miss" in script
    assert "def sample_tool(value" not in script


def test_cached_tool_script_can_omit_source_on_cache_hit() -> None:
    source_hash = tool_source_hash(TOOL_SOURCE)
    script = build_cached_tool_call_script(
        "sample_tool",
        TOOL_SOURCE,
        source_hash,
        {"value": 7},
        include_source=False,
    )

    encoded_source = base64.b64encode(TOOL_SOURCE.encode("utf-8")).decode("ascii")
    assert encoded_source not in script
    assert "_mcp_tool_source_b64 = ''" in script


def test_call_tool_can_disable_cache(monkeypatch, tmp_path: Path) -> None:
    tool_path = tmp_path / "sample_tool.py"
    tool_path.write_text(TOOL_SOURCE, encoding="utf-8")
    sent_scripts = []

    def fake_run(self, python_script):
        sent_scripts.append(python_script)
        return {"success": True}

    monkeypatch.setenv("MAYA_MCP_DISABLE_TOOL_CACHE", "1")
    monkeypatch.setattr(MayaConnection, "run_python_script", fake_run)

    connection = MayaConnection()
    result = connection.call_tool("sample_tool", str(tool_path), {"value": 3})

    assert result == {"success": True}
    assert "def _mcp_maya_scope" in sent_scripts[0]
    assert "def sample_tool" in sent_scripts[0]
