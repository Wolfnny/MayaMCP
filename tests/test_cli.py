from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str, env_updates: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    src_path = str(ROOT / "src")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath
    if env_updates:
        env.update(env_updates)
    return subprocess.run(
        [sys.executable, "-m", "maya_mcp.cli", *args],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def test_cli_help_smoke() -> None:
    result = _run_cli("--help")

    assert result.returncode == 0
    assert "maya-mcp" in result.stdout


def test_doctor_json_without_live_smoke() -> None:
    result = _run_cli("doctor", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["live"]["skipped"] is True
    assert payload["tools"]["discovered_count"] >= 100


def test_tools_json_smoke() -> None:
    result = _run_cli("tools", "--json", "--fail-on-contract")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["tool_count"] >= 100
    assert "object" in payload["categories"]


def test_doctor_json_reports_invalid_connection_config() -> None:
    result = _run_cli(
        "doctor",
        "--json",
        env_updates={"MAYA_MCP_COMMAND_SOURCE_TYPE": "javascript"},
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["connection"]["success"] is False
    assert "mel or python" in payload["connection"]["message"]
