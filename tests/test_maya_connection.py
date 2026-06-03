from __future__ import annotations

import json
import re

import pytest

from maya_mcp.server import (
    MayaConnection,
    RESIDENT_EXECUTOR_VERSION,
    _KNOWN_MAYA_RESIDENT_EXECUTOR_KEYS,
    build_cached_tool_call_script,
)


def test_connection_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAYA_MCP_COMMAND_HOST", "127.0.0.2")
    monkeypatch.setenv("MAYA_MCP_COMMAND_PORT", "50123")
    monkeypatch.setenv("MAYA_MCP_COMMAND_SOURCE_TYPE", "python")

    connection = MayaConnection()

    assert connection.host == "127.0.0.2"
    assert connection.port == 50123
    assert connection.source_type == "python"


def test_connection_rejects_invalid_source_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAYA_MCP_COMMAND_SOURCE_TYPE", "javascript")

    with pytest.raises(ValueError, match="mel or python"):
        MayaConnection()


def test_mel_python_encoding_escapes_code() -> None:
    encoded = MayaConnection._encode_python_to_mel_python('print("a\\\\b")\nprint("c")')

    assert encoded.startswith('python("')
    assert '\\"a\\\\\\\\b\\"' in encoded
    assert "\\n" in encoded


def test_clean_command_result_removes_nulls_and_newlines() -> None:
    assert MayaConnection._clean_command_result("abc\x00\n") == "abc"
    assert MayaConnection._clean_command_result(None) == ""


def test_run_python_script_fetches_current_output_var(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MayaConnection(host="127.0.0.1", port=50007, source_type="mel")
    calls = []

    def fake_send(python_script, *, wrap_python_exec=False):
        calls.append((python_script, wrap_python_exec))
        if len(calls) == 1:
            return '{"success": true, "value": "stale"}'
        request_id = re.search(r"_mcp_maya_result_request_id = '([^']+)'", calls[0][0]).group(1)
        return json.dumps(
            {
                "request_id": request_id,
                "result": '{"success": true, "value": "fresh"}',
            }
        )

    monkeypatch.setattr(connection, "_send_python_command", fake_send)

    result = connection.run_python_script("pass")

    assert result == {"success": True, "value": "fresh"}
    assert "_mcp_maya_results" in calls[1][0]
    assert "_mcp_maya_result_request_id" in calls[1][0]
    assert calls[1][1] is False


def test_run_python_script_ignores_stale_output_var_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MayaConnection(host="127.0.0.1", port=50007, source_type="mel")
    calls = []

    def fake_send(python_script, *, wrap_python_exec=False):
        calls.append((python_script, wrap_python_exec))
        if len(calls) == 1:
            return '{"success": true, "value": "initial"}'
        return json.dumps(
            {
                "request_id": "stale-request",
                "result": '{"success": true, "value": "stale"}',
            }
        )

    monkeypatch.setattr(connection, "_send_python_command", fake_send)

    result = connection.run_python_script("pass")

    assert result == {"success": True, "value": "initial"}


def test_connection_failure_mentions_effective_configuration() -> None:
    connection = MayaConnection(host="127.0.0.1", port=1, source_type="mel")

    with pytest.raises(ConnectionError) as exc_info:
        connection._send_python_command("print('probe')")

    message = str(exc_info.value)
    assert "host=127.0.0.1" in message
    assert "port=1" in message
    assert "source_type=mel" in message
    assert "commandPort" in message


def test_cached_tool_script_invalidates_cache_on_scene_open() -> None:
    script = build_cached_tool_call_script(
        tool_name="probe_tool",
        source="def probe_tool():\n    return {'success': True}\n",
        source_hash="abc123",
        arguments={},
        include_source=True,
    )

    assert "SceneOpened" in script
    assert "NewSceneOpened" in script
    assert "MSceneMessage" in script
    assert "kBeforeOpen" in script
    assert "kAfterOpen" in script
    assert "_mcp_invalidate_tool_cache_for_scene_change" in script
    assert "_mcp_tool_registry" in script
    assert "scene_invalidations" in script


def test_resident_probe_reinstalls_when_entrypoint_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MayaConnection(host="127.0.0.1", port=50007, source_type="mel")
    _KNOWN_MAYA_RESIDENT_EXECUTOR_KEYS.clear()
    calls = []

    def fake_run(python_script):
        calls.append(python_script)
        if "def _mcp_call_resident_tool" in python_script:
            return {"success": True, "version": RESIDENT_EXECUTOR_VERSION}
        if len([call for call in calls if "def _mcp_call_resident_tool" not in call]) == 1:
            return {
                "success": False,
                "resident_executor": False,
                "version": None,
                "expected_version": RESIDENT_EXECUTOR_VERSION,
            }
        return {
            "success": True,
            "resident_executor": True,
            "version": RESIDENT_EXECUTOR_VERSION,
            "expected_version": RESIDENT_EXECUTOR_VERSION,
        }

    monkeypatch.setattr(connection, "run_python_script", fake_run)

    result = connection.run_resident_probe()

    install_calls = [call for call in calls if "def _mcp_call_resident_tool" in call]
    assert result["success"] is True
    assert result["version"] == RESIDENT_EXECUTOR_VERSION
    assert len(install_calls) == 2
