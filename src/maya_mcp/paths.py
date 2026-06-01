from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIRECTORY = Path(__file__).resolve().parent
SOURCE_DIRECTORY = PACKAGE_DIRECTORY.parent
PROJECT_ROOT = SOURCE_DIRECTORY.parent
DEFAULT_TOOLS_DIRECTORY = SOURCE_DIRECTORY / "mayatools"


def get_tools_directory(value: str | os.PathLike[str] | None = None) -> Path:
    """Return the Maya tool source directory."""
    configured = value or os.environ.get("MAYA_MCP_TOOLS_DIR")
    return Path(configured).resolve() if configured else DEFAULT_TOOLS_DIRECTORY.resolve()


def get_artifact_directory() -> Path:
    """Return the default output directory for generated diagnostics."""
    configured = os.environ.get("MAYA_MCP_ARTIFACT_DIR")
    artifact_dir = Path(configured) if configured else Path.cwd() / ".maya_mcp_artifacts"
    return artifact_dir.resolve()


def get_log_path() -> Path:
    """Return the server log path, honoring explicit user configuration."""
    configured = os.environ.get("MAYA_MCP_LOG_PATH")
    if configured:
        return Path(configured).resolve()
    return get_artifact_directory() / "logs" / "maya_mcp_server.log"
