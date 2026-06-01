from __future__ import annotations

import os
from pathlib import Path

import pytest

from maya_mcp.server import MayaConnection
from maya_mcp.paths import get_tools_directory


pytestmark = pytest.mark.live_maya


def _requires_live_maya() -> None:
    if os.environ.get("MAYA_MCP_LIVE") != "1":
        pytest.skip("Set MAYA_MCP_LIVE=1 to run Maya commandPort tests.")


def test_live_audit_scene_strings_detects_problem_strings() -> None:
    _requires_live_maya()
    connection = MayaConnection()
    state_script = r'''
import json
import maya.cmds as cmds
_mcp_maya_results = json.dumps({
    "success": True,
    "scene": cmds.file(query=True, sceneName=True) or "",
    "modified": bool(cmds.file(query=True, modified=True)),
})
'''
    state = connection.run_python_script(state_script)
    if state.get("modified"):
        pytest.skip("Current Maya scene has unsaved changes; live test will not replace it.")
    original_scene = state.get("scene") or ""
    setup_script = r'''
import json
import os
import tempfile
import maya.cmds as cmds
cmds.file(new=True, force=True)
cjk = "\u4e2d\u6587"
cjk_node_names = True
try:
    transform = cmds.polyCube(name="Coca" + cjk + "_transform")[0]
except Exception:
    cjk_node_names = False
    transform = cmds.polyCube(name="Coca_ascii_transform")[0]
if cjk_node_names:
    shape = (cmds.listRelatives(transform, shapes=True) or [""])[0]
    if shape:
        try:
            cmds.rename(shape, cjk + "_shape")
        except Exception:
            pass
material_name = cjk + "_material" if cjk_node_names else "ascii_material"
sg_name = cjk + "_sg" if cjk_node_names else "ascii_sg"
material = cmds.shadingNode("lambert", asShader=True, name=material_name)
shading_group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sg_name)
cmds.connectAttr(material + ".outColor", shading_group + ".surfaceShader", force=True)
cmds.sets(transform, edit=True, forceElement=shading_group)
file_node_name = cjk + "_file_texture" if cjk_node_names else "ascii_file_texture"
file_node = cmds.shadingNode("file", asTexture=True, name=file_node_name)
cmds.setAttr(file_node + ".fileTextureName", "C:/missing/" + cjk + "_texture.png", type="string")
scene_path = os.path.join(tempfile.gettempdir(), cjk + "_scene.ma").replace("\\", "/")
cmds.file(rename=scene_path)
if cjk_node_names:
    try:
        cmds.createDisplayLayer(name=cjk + "_display_layer", empty=True)
        cmds.sets(name=cjk + "_object_set")
        cmds.namespace(add=cjk + "namespace")
    except Exception:
        pass
_mcp_maya_results = json.dumps({"success": True, "cjk_node_names": cjk_node_names})
'''
    tool_path = Path(get_tools_directory()) / "scene" / "audit_scene_strings.py"
    try:
        setup_result = connection.run_python_script(setup_script)
        assert setup_result["success"] is True

        cjk_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "cjk", "max_results": 2000},
        )
        mid_cache = connection.run_cache_probe()
        second_cjk_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "cjk", "max_results": 2000},
        )
        after_cache = connection.run_cache_probe()

        assert cjk_result["success"] is False
        assert cjk_result["match_count"] > 0
        assert second_cjk_result["match_count"] == cjk_result["match_count"]
        assert after_cache["stats"]["loads"] == mid_cache["stats"]["loads"]
        assert after_cache["stats"]["hits"] > mid_cache["stats"]["hits"]
        assert any(match["category"] == "file_textures" for match in cjk_result["matches"])
        assert any(match["category"] == "scene" for match in cjk_result["matches"])
        assert any(match["path_exists"] is False for match in cjk_result["matches"])

        non_ascii_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "non_ascii", "max_results": 2000},
        )
        assert non_ascii_result["match_count"] >= cjk_result["match_count"]

        custom_result = connection.call_tool(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "custom", "pattern": "texture", "max_results": 2000},
        )
        assert custom_result["match_count"] >= 1
    finally:
        if original_scene:
            cleanup_script = f'''
import json
import maya.cmds as cmds
cmds.file({original_scene!r}, open=True, force=True)
_mcp_maya_results = json.dumps({{"success": True}})
'''
        else:
            cleanup_script = r'''
import json
import maya.cmds as cmds
cmds.file(new=True, force=True)
_mcp_maya_results = json.dumps({"success": True})
'''
        connection.run_python_script(cleanup_script)


def test_live_tool_cache_reloads_when_source_hash_changes(tmp_path: Path) -> None:
    _requires_live_maya()
    connection = MayaConnection()
    tool_path = tmp_path / "cache_probe_tool.py"
    source_one = '''from typing import Any, Dict


def cache_probe_tool(value: int = 1) -> Dict[str, Any]:
    """Return a cache probe result."""
    return {"success": True, "value": value, "version": 1}
'''
    source_two = source_one.replace('"version": 1', '"version": 2')

    tool_path.write_text(source_one, encoding="utf-8")
    first = connection.call_tool("cache_probe_tool", str(tool_path), {"value": 5})
    first_cache = connection.run_cache_probe()

    tool_path.write_text(source_two, encoding="utf-8")
    second = connection.call_tool("cache_probe_tool", str(tool_path), {"value": 5})
    second_cache = connection.run_cache_probe()

    assert first["version"] == 1
    assert second["version"] == 2
    assert second_cache["stats"]["loads"] > first_cache["stats"]["loads"]


def test_live_split_mesh_edges_places_ratio_vertex() -> None:
    _requires_live_maya()
    connection = MayaConnection()
    setup_script = r'''
import json
import re
import maya.cmds as cmds
try:
    cmds.delete("mcp_split_live_tmp")
except Exception:
    pass
mesh = cmds.polyCreateFacet(
    name="mcp_split_live_tmp",
    point=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)],
)[0]
line = (cmds.polyInfo(mesh + ".e[0]", edgeToVertex=True) or [""])[0]
ids = [int(value) for value in re.findall(r"\d+", line)][1:]
points = [cmds.xform(mesh + ".vtx[%d]" % index, query=True, worldSpace=True, translation=True) for index in ids]
expected = [points[0][i] + (points[1][i] - points[0][i]) * 0.25 for i in range(3)]
_mcp_maya_results = json.dumps({"success": True, "mesh": mesh, "expected": expected})
'''
    cleanup_script = r'''
import json
import maya.cmds as cmds
try:
    cmds.delete("mcp_split_live_tmp")
except Exception:
    pass
_mcp_maya_results = json.dumps({"success": True})
'''
    tool_path = Path(get_tools_directory()) / "object" / "split_mesh_edges.py"
    try:
        setup = connection.run_python_script(setup_script)
        assert setup["success"] is True

        result = connection.call_tool(
            "split_mesh_edges",
            str(tool_path),
            {
                "object_name": setup["mesh"],
                "indices": [0],
                "position_mode": "ratio",
                "ratio": 0.25,
                "select_result": True,
            },
        )

        assert result["success"] is True
        assert result["new_vertex_count"] == 1
        assert result["ngon_count_after"] >= result["ngon_count_before"]
        assert result["new_ngon_count_delta"] == 1
        edited = result["edited_vertices_preview"][0]
        for actual, expected in zip(edited["after"], setup["expected"]):
            assert actual == pytest.approx(expected, abs=1.0e-6)
    finally:
        connection.run_python_script(cleanup_script)
