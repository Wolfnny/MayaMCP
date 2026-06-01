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
maya-mcp doctor --fix-script
```

`doctor` reports Python compatibility, dependency import status, tool discovery,
tool contract state, artifact/log paths, and the effective commandPort config.
`doctor --live` runs a read-only Maya probe and prints both the matching
commandPort MEL command and the recommended `50009/python` command.
`doctor --fix-script` prints the recommended Maya Script Editor command and MCP
client environment snippet.

## Runtime Cost Controls

MayaMCP caches loaded tool functions inside Maya by `tool_name + source_hash`.
The first call after a server/Maya restart sends the full source; later calls
send only the tool name, hash, and JSON arguments. Set
`MAYA_MCP_DISABLE_TOOL_CACHE=1` to force the full-source path when debugging.

Large JSON results are compacted at the server boundary. The returned payload
keeps counts, previews, `truncated=True`, and an artifact path. The full result
is written under `.maya_mcp_artifacts/results/`. Set
`MAYA_MCP_RESULT_MAX_BYTES=0` to disable compaction or set it to a byte limit.

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
maya-mcp tools --brief
maya-mcp tools search "uv face"
```

Generate a new tool and matching contract test from the template:

```shell
maya-mcp new-tool object/my_tool
```

Regenerate the local tool index:

```shell
maya-mcp docs tools
maya-mcp docs tools --check
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
