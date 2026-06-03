from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from maya_mcp.cli import _print_doctor_human


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


def test_tools_brief_smoke() -> None:
    result = _run_cli("tools", "--brief", "--category", "object")

    assert result.returncode == 0, result.stderr
    assert "[object]" in result.stdout
    assert "select_mesh_by_region" in result.stdout


def test_tools_search_smoke() -> None:
    result = _run_cli("tools", "search", "uv face")

    assert result.returncode == 0, result.stderr
    assert "matches" in result.stdout
    assert "uv" in result.stdout.lower()


def test_doctor_fix_script_smoke() -> None:
    result = _run_cli("doctor", "--fix-script")

    assert result.returncode == 0, result.stderr
    assert 'commandPort -name ":50009"' in result.stdout
    assert "MAYA_MCP_COMMAND_SOURCE_TYPE" in result.stdout


def test_new_tool_dry_run_smoke() -> None:
    result = _run_cli("new-tool", "object/example_tool", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "example_tool.py" in result.stdout
    assert "Dry run only" in result.stdout


def test_docs_tools_check_smoke() -> None:
    result = _run_cli("docs", "tools", "--check")

    assert result.returncode == 0, result.stderr
    assert "docs\\tools.md" in result.stdout or "docs/tools.md" in result.stdout


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


def test_doctor_human_reports_resident_executor(capsys) -> None:
    _print_doctor_human(
        {
            "python": {"version": "3.14.2", "success": True},
            "tools": {"discovered_count": 106, "contract_issue_count": 0},
            "connection": {
                "host": "127.0.0.1",
                "port": 50009,
                "source_type": "python",
                "matching_command_port_mel": 'commandPort -name ":50009";',
                "recommended_python_command_port_mel": 'commandPort -name ":50009";',
            },
            "artifacts": {"artifact_directory": ".maya_mcp_artifacts", "log_path": "maya_mcp_server.log"},
            "live": {
                "requested": True,
                "success": True,
                "command_port_executable": True,
                "resident_executor": True,
                "resident_version": "unit-test-version",
                "cache_writable": True,
                "effective_source_type": "python",
                "recommended_source_type": "python",
            },
        }
    )

    output = capsys.readouterr().out
    assert "Live resident executor: ok (unit-test-version)" in output
