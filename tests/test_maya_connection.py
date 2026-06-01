from __future__ import annotations

import pytest

from maya_mcp.server import MayaConnection


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


def test_connection_failure_mentions_effective_configuration() -> None:
    connection = MayaConnection(host="127.0.0.1", port=1, source_type="mel")

    with pytest.raises(ConnectionError) as exc_info:
        connection._send_python_command("print('probe')")

    message = str(exc_info.value)
    assert "host=127.0.0.1" in message
    assert "port=1" in message
    assert "source_type=mel" in message
    assert "commandPort" in message
