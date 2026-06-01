from __future__ import annotations

from pathlib import Path

from mayatools.common.results import compact_result, preview_list


def test_preview_list_marks_truncation() -> None:
    preview = preview_list([1, 2, 3], limit=2)

    assert preview == {"count": 3, "preview": [1, 2], "truncated": True}


def test_compact_result_writes_artifact_for_large_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAYA_MCP_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("MAYA_MCP_RESULT_MAX_BYTES", "120")
    payload = {
        "success": True,
        "match_count": 20,
        "matches": [{"index": index, "value": "x" * 20} for index in range(20)],
    }

    compacted = compact_result(payload, prefix="unit_test", preview_items=2)

    assert compacted["success"] is True
    assert compacted["compacted"] is True
    assert compacted["truncated"] is True
    assert compacted["match_count"] == 20
    assert compacted["matches_count"] == 20
    assert len(compacted["matches_preview"]) == 2
    assert Path(compacted["artifact_path"]).exists()


def test_compact_result_can_be_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAYA_MCP_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("MAYA_MCP_RESULT_MAX_BYTES", "0")
    payload = {"success": True, "items": list(range(100))}

    assert compact_result(payload, prefix="unit_test") is payload
