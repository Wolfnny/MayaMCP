from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_RESULT_MAX_BYTES = 120000
DEFAULT_PREVIEW_ITEMS = 5


def _artifact_root() -> Path:
    configured = os.environ.get("MAYA_MCP_ARTIFACT_DIR")
    return (Path(configured) if configured else Path.cwd() / ".maya_mcp_artifacts").resolve()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "result"


def _result_limit_bytes() -> int:
    raw_value = os.environ.get("MAYA_MCP_RESULT_MAX_BYTES", str(DEFAULT_RESULT_MAX_BYTES))
    try:
        return max(0, int(raw_value))
    except ValueError:
        return DEFAULT_RESULT_MAX_BYTES


def preview_list(values: List[Any], limit: int = DEFAULT_PREVIEW_ITEMS) -> Dict[str, Any]:
    """Return a compact preview record for a list."""
    clean_limit = max(0, int(limit))
    return {
        "count": len(values),
        "preview": values[:clean_limit],
        "truncated": len(values) > clean_limit,
    }


def write_artifact_json(value: Any, prefix: str = "result") -> str:
    """Write a JSON artifact under .maya_mcp_artifacts/results."""
    destination = _artifact_root() / "results"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{stamp}_{_safe_name(prefix)}_{uuid.uuid4().hex[:8]}.json"
    path = destination / filename
    path.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _compact_dict(value: Dict[str, Any], artifact_path: str, original_size: int, preview_items: int) -> Dict[str, Any]:
    compacted: Dict[str, Any] = {}
    for key in ("success", "message", "error", "tool", "operation"):
        if key in value and (isinstance(value[key], (str, int, float, bool)) or value[key] is None):
            compacted[key] = value.get(key)

    for key, item in value.items():
        if key in compacted:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            if key.endswith("_count") or key in {"count", "match_count", "scanned_count", "changed_count"}:
                compacted[key] = item
        elif isinstance(item, list):
            compacted[f"{key}_count"] = len(item)
            compacted[f"{key}_preview"] = item[:preview_items]
            compacted[f"{key}_truncated"] = len(item) > preview_items

    compacted["success"] = value.get("success", compacted.get("success", True))
    compacted["message"] = (
        f"Result exceeded MAYA_MCP_RESULT_MAX_BYTES; full JSON written to {artifact_path}."
    )
    compacted["truncated"] = True
    compacted["compacted"] = True
    compacted["original_size_bytes"] = original_size
    compacted["artifact_path"] = artifact_path
    return compacted


def compact_result(value: Any, prefix: str = "result", preview_items: int = DEFAULT_PREVIEW_ITEMS) -> Any:
    """Compact oversized result payloads and write the full result to an artifact."""
    max_bytes = _result_limit_bytes()
    if max_bytes == 0:
        return value

    serialized = _json_dumps(value)
    size = len(serialized.encode("utf-8"))
    if size <= max_bytes:
        return value

    artifact_path = write_artifact_json(value, prefix=prefix)
    if isinstance(value, dict):
        return _compact_dict(value, artifact_path, size, preview_items)
    if isinstance(value, list):
        preview = preview_list(value, preview_items)
        return {
            "success": True,
            "message": f"Result exceeded MAYA_MCP_RESULT_MAX_BYTES; full JSON written to {artifact_path}.",
            "truncated": True,
            "compacted": True,
            "original_size_bytes": size,
            "artifact_path": artifact_path,
            "result_count": preview["count"],
            "result_preview": preview["preview"],
            "result_preview_truncated": preview["truncated"],
        }
    return {
        "success": True,
        "message": f"Result exceeded MAYA_MCP_RESULT_MAX_BYTES; full JSON written to {artifact_path}.",
        "truncated": True,
        "compacted": True,
        "original_size_bytes": size,
        "artifact_path": artifact_path,
    }
