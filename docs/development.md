# MayaMCP Development Workflow

## Setup

```shell
python -m venv .venv
.venv\Scripts\activate.bat
pip install -e ".[dev]"
```

The package exposes `maya-mcp`, while `python src/maya_mcp_server.py` remains a
compatibility entrypoint for existing MCP client configurations.

## Diagnostics

```shell
maya-mcp doctor
maya-mcp doctor --json
maya-mcp doctor --live
```

`doctor` reports Python compatibility, dependency import status, tool discovery,
tool contract state, artifact/log paths, and the effective commandPort config.
`doctor --live` runs a read-only Maya probe and prints both the matching
commandPort MEL command and the recommended `50009/python` command.

## Tool Contracts

Each tool file under `src/mayatools` should keep these rules:

- File name and function name must match.
- The module must import in standalone Python.
- Do not import `maya.cmds` or other Maya modules at top level.
- Every parameter must have a type annotation.
- The function must have a docstring.
- MCP schema generation must succeed.

Run:

```shell
maya-mcp tools --fail-on-contract
```

## Tests

Static checks:

```shell
python -m pytest
```

Live Maya checks:

```shell
MAYA_MCP_LIVE=1 python -m pytest -m live_maya
```

The live audit test creates a temporary unsaved scene with intentionally unsafe
strings and verifies `audit_scene_strings` catches them.

## Artifacts

Generated diagnostics, playblasts, reports, and logs should go under
`.maya_mcp_artifacts/`, which is ignored by git. Use `MAYA_MCP_ARTIFACT_DIR` to
move the default root and `MAYA_MCP_LOG_PATH` to override the server log file.
