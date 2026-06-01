from __future__ import annotations

import os
from pathlib import Path

import pytest

from maya_mcp.server import MayaConnection, load_maya_tool_source
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

        cjk_script = load_maya_tool_source(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "cjk", "max_results": 2000},
        )
        cjk_result = connection.run_python_script(cjk_script)

        assert cjk_result["success"] is False
        assert cjk_result["match_count"] > 0
        assert any(match["category"] == "file_textures" for match in cjk_result["matches"])
        assert any(match["category"] == "scene" for match in cjk_result["matches"])
        assert any(match["path_exists"] is False for match in cjk_result["matches"])

        non_ascii_script = load_maya_tool_source(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "non_ascii", "max_results": 2000},
        )
        non_ascii_result = connection.run_python_script(non_ascii_script)
        assert non_ascii_result["match_count"] >= cjk_result["match_count"]

        custom_script = load_maya_tool_source(
            "audit_scene_strings",
            str(tool_path),
            {"preset": "custom", "pattern": "texture", "max_results": 2000},
        )
        custom_result = connection.run_python_script(custom_script)
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
